"""
ai.core.feature_flags — Phase 11 feature-flag service.

Resolution order (first hit wins):

  1. Per-entity override (``entity.metadata_extensions.feature_flags``).
  2. Per-company row in the ``feature_flags`` table.
  3. Global row (``company_id IS NULL``) in the ``feature_flags`` table.
  4. Environment variable: ``AI_FLAG_<KEY>`` (e.g.
     ``AI_FLAG_AGENT_LOOP_ENABLED=true``; a number for a numeric flag,
     ``AI_FLAG_BANDIT_EPSILON=0.2`` — GH-13).
  5. Hard-coded default from ``DEFAULTS`` (``NUMERIC_DEFAULTS``) below.

Numeric flags read the database rows' ``value_json`` with ``get_float``; both
kinds report the tier their value came from (``resolve`` / ``resolve_float``).

Flags are engineering switches, staff-only (Phase 15 Q6, T0-1): the admin API
writes a declared key only (``flag_kind``), for ``app_admin`` only, and every
write leaves an ``admin_audit_log`` row (``src.common.admin_audit``).

The DB table is OPTIONAL — if Alembic hasn't run the migration yet,
flags fall through to env vars + defaults instead of raising. That
makes the system safe to deploy in any order.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID


def _sandbox_container_default() -> bool:
    """The deployment's default for ``sandbox.container_runtime_enabled``."""
    try:
        from src.common.config import settings
        return bool(settings.SANDBOX_CONTAINER_RUNTIME_ENABLED)
    except Exception:                                                     # pragma: no cover
        return True   # the container is the safe default (TL-01)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Defaults — the source of truth when no DB / env override exists.
# Per Track 2 plan §8.
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, bool] = {
    # A declared flag must have a reader (AK-10). ``tests/unit/
    # test_feature_flag_census.py`` fails when a key here is read by nothing
    # outside this module; the few known exceptions are listed there with the
    # phase that decides them.
    #
    # The AgentLoop is the sole run engine (C4 deleted the legacy
    # ExecutionEngine.execute_run path), so the ``agent_loop.enabled`` master
    # switch no longer exists. The remaining ``agent_loop.*`` flags tune
    # behaviour WITHIN the loop.
    #
    # Write one AgentState snapshot node into the run's CORTEX tree per
    # iteration (it feeds the /agent_state rail). Off saves one write per
    # iteration; a suspended run's resumable snapshot is separate and unaffected.
    "agent_loop.snapshot_every_iteration": True,
    # Budget-aware REACT (Phase 12 `07` §2): thread budget pressure into the
    # step prompt as a soft constraint, with an explicit "finish, don't expand"
    # directive past ``agent_loop.budget_pressure_threshold``. The hard engine
    # cap still applies; this nudges the LLM to plan within budget. Default ON.
    "agent_loop.budget_aware_react": True,
    # Critic pipeline v2 defaults.
    "critic_pipeline.v2_enabled": True,
    "critic_pipeline.different_model_critic": True,
    "critic_pipeline.pre_critic_enabled": True,
    # (C1: critic_pipeline.v1_compat retired — the v1 critic body is deleted.)
    # Weekly critic calibration per company (critic_calibration_job).
    "critic_pipeline.calibration_enabled": True,
    "bandit.enabled": True,
    "task_classifier.v2_enabled": False,
    # The two weekly Meta-Agent crons (skill_promotion_scan,
    # meta_agent_prompt_evolution) skip when their flag is off.
    "meta_agent.skill_promotion_cron": True,
    "meta_agent.prompt_evolution_cron": True,
    # Tool synthesis kill switch (Phase 12 `06` §2.2 control 5). Default OFF;
    # the marquee/most-dangerous capability. Even when ON, the tool_synthesis
    # meta-tool stays Meta-Agent-only + container-only-exec + DRAFT-register-only.
    "meta_agent.tool_synthesis_enabled": False,
    # Tool & cost consolidation defaults. (tools.cost_resolver_v2_enabled is
    # gone: ToolCostResolver is the only tool price lookup, unconditionally —
    # BC-17. The flag was declared and never read.)
    # Planner v2 (multi-candidate generation + invariants + judge).
    "planner.v2_enabled": True,
    # Per-tenant container sandbox (Phase 12 `02` S4) — THE switch (TX-01):
    # company row, then global row, then AI_FLAG_ env, then this default, which
    # is the deployment's SANDBOX_CONTAINER_RUNTIME_ENABLED (on since TL-01). It
    # was declared True here while the runtime ignored it and ran the host sandbox.
    "sandbox.container_runtime_enabled": _sandbox_container_default(),
    # Per-tenant persistent browser profile canary (Phase 12 `02` S5). Default
    # OFF (ephemeral context). Resolved per-company and threaded into the tool
    # context as ``persistent_browser``; master is
    # settings.SANDBOX_PERSISTENT_BROWSER_ENABLED.
    "sandbox.persistent_browser_enabled": False,
    # Whom video_generate may depict (TL-46): off sends Veo
    # person_generation="allow_adult" (Veo's own default, allowed everywhere);
    # a company that turns this on gets "allow_all", which includes minors and
    # is restricted in some regions. It was hardcoded "allow_all" for everyone.
    "tools.video.people_of_all_ages": False,
    # Memory v2 canonicalisation defaults. (memory.viewport_compact,
    # memory.scope_policy_enforced, memory.embedding_resolver_v2 and the alias
    # memory_v2.canonical were deleted: nothing read them, so they controlled
    # nothing — GH-15, GH-16.)
    "memory.v2_canonical": True,
    "memory.dreaming_outcome_trigger": True,
    # IntelligenceTree rule lifecycle (Phase 12 `06` §5): when ON, only
    # `confirmed` rules (candidate→confirmed→retired) enter planner/critic
    # prompts. Retired rules are always dropped; default OFF keeps legacy
    # (lifecycle-less) rules eligible so enabling never blanks prompts.
    "memory.rule_lifecycle_confirmed_only": False,
}


# ---------------------------------------------------------------------------
# Numeric / float feature flags — separate dict so the bool resolver
# above stays simple. Reading code must use ``get_float`` explicitly.
# ---------------------------------------------------------------------------

NUMERIC_DEFAULTS: dict[str, float] = {
    "bandit.epsilon": 0.10,
    # Budget pressure (0..1) past which budget-aware REACT injects the explicit
    # "finish, don't expand" directive (Phase 12 `07` §2).
    "agent_loop.budget_pressure_threshold": 0.70,
    # Meta-Agent test driver suite budget (USD). Gates the unwired Board (MI-20).
    # Planner candidate count.
    "planner.n_candidates": 3,
}


# A company's opt-in to one EXPERIMENTAL/DRAFT tool (TL-13): the only family of
# keys not listed above, since there is one per tool.
EXPERIMENTAL_TOOL_PREFIX = "tools.experimental."
_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def flag_kind(flag_key: str) -> Optional[str]:
    """``boolean`` or ``numeric`` for a declared flag; ``None`` for a key nothing reads.

    The admin API writes only declared keys (Phase 15 T0-1): a typo used to
    create a row that no code ever read.
    """
    if flag_key in DEFAULTS:
        return "boolean"
    if flag_key in NUMERIC_DEFAULTS:
        return "numeric"
    if flag_key.startswith(EXPERIMENTAL_TOOL_PREFIX) and _TOOL_NAME.match(flag_key[len(EXPERIMENTAL_TOOL_PREFIX):]):
        return "boolean"
    return None


def _env_name(key: str) -> str:
    return "AI_FLAG_" + key.upper().replace(".", "_")


def _env_lookup(key: str) -> Optional[bool]:
    raw = os.environ.get(_env_name(key))
    if raw is None:
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(key: str) -> Optional[float]:
    """A numeric flag from ``AI_FLAG_<KEY>`` (GH-13); a value that is not a
    number is ignored, and said so."""
    raw = os.environ.get(_env_name(key))
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw)
    except ValueError:
        logger.warning("%s=%r is not a number; %s falls through to its default", _env_name(key), raw, key)
        return None


@dataclass
class _Resolution:
    value: bool
    source: str           # "entity", "company", "global", "env", "default"
    flag_key: str


def _on_control_plane() -> dict[str, Any]:
    """``bind_arguments`` that send a ``feature_flags`` statement to the control
    database whichever session runs it — often a run's tenant session (Phase 14
    WS2). With one database they change nothing."""
    from src.ai.orm.feature_flags import FeatureFlag

    return {"mapper": FeatureFlag}


_REDIS_INVALIDATION_CHANNEL = "feature_flag_invalidations"
_PROCESS_CACHE_TTL_SECONDS = 60


class _ProcessCacheEntry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: _Resolution, expires_at: float):
        self.value = value
        self.expires_at = expires_at


_PROCESS_CACHE: dict[tuple[str, Optional[str], Optional[str]], _ProcessCacheEntry] = {}


def _process_cache_get(
    flag_key: str, company_id: Optional[str], entity_id: Optional[str],
) -> Optional[_Resolution]:
    import time
    key = (flag_key, company_id, entity_id)
    entry = _PROCESS_CACHE.get(key)
    if entry is None or entry.expires_at < time.time():
        if entry is not None:
            _PROCESS_CACHE.pop(key, None)
        return None
    return entry.value


def _process_cache_put(
    flag_key: str, company_id: Optional[str], entity_id: Optional[str],
    value: _Resolution,
) -> None:
    import time
    _PROCESS_CACHE[(flag_key, company_id, entity_id)] = _ProcessCacheEntry(
        value=value, expires_at=time.time() + _PROCESS_CACHE_TTL_SECONDS,
    )


def invalidate_process_cache(flag_key: Optional[str] = None) -> None:
    """Drop process-level cache entries; pass a flag_key to evict one."""
    if flag_key is None:
        _PROCESS_CACHE.clear()
        return
    keys = [k for k in _PROCESS_CACHE if k[0] == flag_key]
    for k in keys:
        _PROCESS_CACHE.pop(k, None)


# ---------------------------------------------------------------------------
# Every process's cache (GH-14)
# ---------------------------------------------------------------------------
# Each API and worker process caches resolved flags for a minute. A change
# made through ``FeatureFlags.set`` / ``delete`` is published on
# ``feature_flag_invalidations`` once it commits, and every process runs
# :func:`listen_for_invalidations`, which drops the flag there. A change made
# with SQL is announced with ``POST /api/v1/ai/admin/feature_flags/invalidate``.
# Before, nothing listened, the admin endpoint published with no Redis client,
# and the experimental-tool toggle wrote raw SQL: up to a minute of staleness
# in every process.

_LISTEN_RETRY_SECONDS = 5.0


async def publish_invalidation(
    flag_key: Optional[str] = None,
    *,
    company_id: Optional[UUID] = None,
    entity_id: Optional[UUID] = None,
    redis: Any = None,
) -> bool:
    """Drop ``flag_key`` (every flag when None) here and in every process."""
    import json as _json

    invalidate_process_cache(flag_key)
    try:
        if redis is None:
            from src.common.redis_client import shared_redis
            redis = shared_redis()
        await redis.publish(_REDIS_INVALIDATION_CHANNEL, _json.dumps({
            "flag_key": flag_key,
            "company_id": str(company_id) if company_id else None,
            "entity_id": str(entity_id) if entity_id else None,
        }))
        return True
    except Exception as exc:                                              # noqa: BLE001
        logger.warning("Flag %s changed; other processes keep it until their cache expires (%ss): %s",
                       flag_key or "*", _PROCESS_CACHE_TTL_SECONDS, exc)
        return False


async def listen_for_invalidations(redis_url: str) -> None:
    """Drop a flag from this process's cache when any process announces it changed.

    Runs for the life of the process (the API's lifespan, each worker's
    startup); a process that loses the channel drops its whole cache when it
    is back, for what it may have missed.
    """
    import asyncio
    import json as _json

    import redis.asyncio as redis_lib

    while True:
        client = redis_lib.from_url(redis_url)  # type: ignore[no-untyped-call]
        pubsub = client.pubsub()
        try:
            await pubsub.subscribe(_REDIS_INVALIDATION_CHANNEL)
            invalidate_process_cache()
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if not message or message.get("type") != "message":
                    continue
                try:
                    flag_key = _json.loads(message.get("data") or "{}").get("flag_key")
                except (TypeError, ValueError, AttributeError):
                    flag_key = None                  # unreadable: drop everything
                invalidate_process_cache(flag_key)
        except asyncio.CancelledError:
            raise
        except Exception as exc:                                          # noqa: BLE001
            logger.warning("Flag invalidation channel lost (%s); retrying in %ss", exc, _LISTEN_RETRY_SECONDS)
            await asyncio.sleep(_LISTEN_RETRY_SECONDS)
        finally:
            try:
                await pubsub.aclose()
                await client.aclose()
            except Exception:                                             # noqa: BLE001
                pass


class FeatureFlags:
    """Async service. Construct one per Arq job / request — short-lived.

    ``db`` may be None when no DB session is available; the service
    falls through to env + defaults in that case.
    """

    def __init__(self, db: Any = None, *, redis: Any = None):
        self.db = db
        self.redis = redis
        self._cache: dict[tuple[str, Optional[str]], _Resolution] = {}

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    async def is_on(
        self,
        flag_key: str,
        *,
        company_id: Optional[UUID] = None,
        entity_id: Optional[UUID] = None,
        entity_extras: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Return True if the flag is enabled for this (entity, company) scope."""
        resolution = await self._resolve(
            flag_key, company_id, entity_id, entity_extras,
        )
        return resolution.value

    async def resolve(
        self,
        flag_key: str,
        *,
        company_id: Optional[UUID] = None,
        entity_id: Optional[UUID] = None,
        entity_extras: Optional[dict[str, Any]] = None,
    ) -> _Resolution:
        return await self._resolve(
            flag_key, company_id, entity_id, entity_extras,
        )

    async def get_float(
        self,
        flag_key: str,
        *,
        company_id: Optional[UUID] = None,
        entity_id: Optional[UUID] = None,
        default: Optional[float] = None,
    ) -> float:
        """Resolve a numeric flag (``bandit.epsilon``, ``planner.n_candidates``).

        Order: per-entity ``value_json`` → per-company ``value_json``
        → global ``value_json`` → ``AI_FLAG_<KEY>`` (GH-13; numeric flags
        had no env tier, so they could not be set without a database row)
        → ``NUMERIC_DEFAULTS[flag_key]`` → ``default`` (caller fallback, 0.0
        if not given).
        """
        value, _source = await self.resolve_float(flag_key, company_id=company_id,
                                                  entity_id=entity_id, default=default)
        return value

    async def resolve_float(
        self,
        flag_key: str,
        *,
        company_id: Optional[UUID] = None,
        entity_id: Optional[UUID] = None,
        default: Optional[float] = None,
    ) -> tuple[float, str]:
        """A numeric flag's value and the tier it came from (``get_float``'s order)."""
        if self.db is not None:
            for c_id, e_id in self._db_scope_chain(company_id, entity_id):
                val = await self._db_lookup_value_json(flag_key, c_id, e_id)
                if val is None:
                    continue
                try:
                    return float(val), ("entity_row" if e_id else "company" if c_id else "global")
                except (TypeError, ValueError):
                    continue
        env_val = _env_float(flag_key)
        if env_val is not None:
            return env_val, "env"
        if flag_key in NUMERIC_DEFAULTS:
            return float(NUMERIC_DEFAULTS[flag_key]), "default"
        return float(default if default is not None else 0.0), "caller_default"

    async def set(
        self,
        flag_key: str,
        *,
        enabled: Optional[bool] = None,
        value_json: Any = None,
        company_id: Optional[UUID] = None,
        entity_id: Optional[UUID] = None,
    ) -> None:
        """Upsert a feature flag at the (company, entity) scope and
        publish an invalidation event so other workers drop their cache.

        Either ``enabled`` or ``value_json`` (or both) MUST be provided.
        """
        if enabled is None and value_json is None:
            raise ValueError("set(): supply at least one of enabled / value_json")
        if self.db is None:
            raise RuntimeError("set(): db session required")
        import json as _json
        from sqlalchemy import text as _t
        # ON CONFLICT targets MUST match the partial-unique-index columns
        # AND predicate exactly. See p11t02_feature_flags migration:
        #   entity tier:  (flag_key, entity_id)        WHERE entity_id IS NOT NULL
        #   company tier: (flag_key, company_id)       WHERE company_id IS NOT NULL
        #                                              AND entity_id IS NULL
        #   global tier:  (flag_key)                   WHERE company_id IS NULL
        #                                              AND entity_id IS NULL
        if entity_id is not None:
            stmt = _t(
                """
                INSERT INTO feature_flags (
                    id, company_id, entity_id, flag_key,
                    enabled, value_json, created_at, updated_at
                ) VALUES (
                    gen_random_uuid(), :c, :e, :k,
                    COALESCE(:enabled, false),
                    CAST(:value_json AS json),
                    now(), now()
                )
                ON CONFLICT (flag_key, entity_id)
                  WHERE entity_id IS NOT NULL
                DO UPDATE SET
                    enabled = COALESCE(EXCLUDED.enabled, feature_flags.enabled),
                    value_json = CASE WHEN EXCLUDED.value_json IS NOT NULL
                                      THEN EXCLUDED.value_json
                                      ELSE feature_flags.value_json END,
                    updated_at = now()
                """
            )
        elif company_id is not None:
            stmt = _t(
                """
                INSERT INTO feature_flags (
                    id, company_id, entity_id, flag_key,
                    enabled, value_json, created_at, updated_at
                ) VALUES (
                    gen_random_uuid(), :c, NULL, :k,
                    COALESCE(:enabled, false),
                    CAST(:value_json AS json),
                    now(), now()
                )
                ON CONFLICT (flag_key, company_id)
                  WHERE company_id IS NOT NULL AND entity_id IS NULL
                DO UPDATE SET
                    enabled = COALESCE(EXCLUDED.enabled, feature_flags.enabled),
                    value_json = CASE WHEN EXCLUDED.value_json IS NOT NULL
                                      THEN EXCLUDED.value_json
                                      ELSE feature_flags.value_json END,
                    updated_at = now()
                """
            )
        else:
            stmt = _t(
                """
                INSERT INTO feature_flags (
                    id, company_id, entity_id, flag_key,
                    enabled, value_json, created_at, updated_at
                ) VALUES (
                    gen_random_uuid(), NULL, NULL, :k,
                    COALESCE(:enabled, false),
                    CAST(:value_json AS json),
                    now(), now()
                )
                ON CONFLICT (flag_key)
                  WHERE company_id IS NULL AND entity_id IS NULL
                DO UPDATE SET
                    enabled = COALESCE(EXCLUDED.enabled, feature_flags.enabled),
                    value_json = CASE WHEN EXCLUDED.value_json IS NOT NULL
                                      THEN EXCLUDED.value_json
                                      ELSE feature_flags.value_json END,
                    updated_at = now()
                """
            )
        await self.db.execute(
            stmt,
            {
                "k": flag_key,
                "c": str(company_id) if company_id else None,
                "e": str(entity_id) if entity_id else None,
                "enabled": enabled,
                "value_json": _json.dumps(value_json) if value_json is not None else None,
            },
            bind_arguments=_on_control_plane(),
        )
        invalidate_process_cache(flag_key)
        await self._announce_after_commit(flag_key, company_id, entity_id)

    async def delete(
        self,
        flag_key: str,
        *,
        company_id: Optional[UUID] = None,
        entity_id: Optional[UUID] = None,
    ) -> bool:
        """Remove the row at the exact (company, entity) scope. Returns
        True when a row was actually deleted.
        """
        if self.db is None:
            raise RuntimeError("delete(): db session required")
        from sqlalchemy import text as _t
        if entity_id is not None:
            where = "entity_id = :e AND company_id = :c"
        elif company_id is not None:
            where = "company_id = :c AND entity_id IS NULL"
        else:
            where = "company_id IS NULL AND entity_id IS NULL"
        result = await self.db.execute(
            _t(f"DELETE FROM feature_flags WHERE flag_key = :k AND {where}"),
            {
                "k": flag_key,
                "c": str(company_id) if company_id else None,
                "e": str(entity_id) if entity_id else None,
            },
            bind_arguments=_on_control_plane(),
        )
        affected = (result.rowcount or 0) > 0
        if affected:
            invalidate_process_cache(flag_key)
            await self._announce_after_commit(flag_key, company_id, entity_id)
        return affected

    async def _announce_after_commit(
        self,
        flag_key: str,
        company_id: Optional[UUID],
        entity_id: Optional[UUID],
    ) -> None:
        """Tell every process once the caller's transaction commits (GH-14).

        Published before the commit, another process would re-read the old
        row and cache it for a minute. A session with no transaction to wait
        for (a test double) publishes now.
        """
        sync_session = getattr(self.db, "sync_session", None)
        if sync_session is None:
            await self._publish_invalidation(flag_key, company_id, entity_id)
            return
        import asyncio
        from sqlalchemy import event

        loop = asyncio.get_running_loop()

        def _committed(_session: Any) -> None:
            invalidate_process_cache(flag_key)   # sessions of this process that read meanwhile
            loop.create_task(self._publish_invalidation(flag_key, company_id, entity_id))

        event.listen(sync_session, "after_commit", _committed, once=True)

    async def _publish_invalidation(
        self,
        flag_key: Optional[str],
        company_id: Optional[UUID] = None,
        entity_id: Optional[UUID] = None,
    ) -> None:
        await publish_invalidation(flag_key, company_id=company_id, entity_id=entity_id, redis=self.redis)

    async def _resolve(
        self,
        flag_key: str,
        company_id: Optional[UUID],
        entity_id: Optional[UUID],
        entity_extras: Optional[dict[str, Any]],
    ) -> _Resolution:
        # 1. Per-entity override embedded in entity.metadata_extensions.
        if entity_extras:
            override = self._read_entity_extras(flag_key, entity_extras)
            if override is not None:
                return _Resolution(value=override, source="entity", flag_key=flag_key)

        # 2/3/4. DB lookups, with process-level cache.
        if self.db is not None:
            cached = _process_cache_get(
                flag_key,
                str(company_id) if company_id else None,
                str(entity_id) if entity_id else None,
            )
            if cached is not None:
                return cached
            db_val = await self._db_lookup(flag_key, company_id, entity_id)
            if db_val is not None:
                _process_cache_put(
                    flag_key,
                    str(company_id) if company_id else None,
                    str(entity_id) if entity_id else None,
                    db_val,
                )
                return db_val

        # 5. Env var fallback.
        env_val = _env_lookup(flag_key)
        if env_val is not None:
            return _Resolution(value=env_val, source="env", flag_key=flag_key)

        # 6. Defaults.
        return _Resolution(
            value=DEFAULTS.get(flag_key, False),
            source="default",
            flag_key=flag_key,
        )

    @staticmethod
    def _db_scope_chain(
        company_id: Optional[UUID], entity_id: Optional[UUID],
    ) -> list[tuple[Optional[UUID], Optional[UUID]]]:
        """Iterate (company_id, entity_id) tuples in priority order."""
        chain: list[tuple[Optional[UUID], Optional[UUID]]] = []
        if entity_id is not None and company_id is not None:
            chain.append((company_id, entity_id))
        if company_id is not None:
            chain.append((company_id, None))
        chain.append((None, None))
        return chain

    async def _db_lookup_value_json(
        self,
        flag_key: str,
        company_id: Optional[UUID],
        entity_id: Optional[UUID],
    ) -> Any:
        """Return ``value_json`` for the row at the exact scope, or None."""
        try:
            from sqlalchemy import text
            if entity_id is not None:
                where = "company_id = :c AND entity_id = :e"
            elif company_id is not None:
                where = "company_id = :c AND entity_id IS NULL"
            else:
                where = "company_id IS NULL AND entity_id IS NULL"
            row = (await self.db.execute(
                text(
                    f"SELECT value_json FROM feature_flags "
                    f"WHERE flag_key = :k AND {where}"
                ),
                {
                    "k": flag_key,
                    "c": str(company_id) if company_id else None,
                    "e": str(entity_id) if entity_id else None,
                },
                bind_arguments=_on_control_plane(),
            )).first()
            return row[0] if row is not None else None
        except Exception:                                                     # pragma: no cover
            return None

    # ------------------------------------------------------------------
    # Source readers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_entity_extras(flag_key: str, extras: dict[str, Any]) -> Optional[bool]:
        feature_flags = extras.get("feature_flags") if isinstance(extras, dict) else None
        if not isinstance(feature_flags, dict):
            return None
        # Accept either flat key or namespaced ("agent_loop": {"enabled": true}).
        if flag_key in feature_flags:
            v = feature_flags[flag_key]
            return bool(v) if isinstance(v, (bool, int)) else None
        if "." in flag_key:
            head, tail = flag_key.split(".", 1)
            ns = feature_flags.get(head)
            if isinstance(ns, dict) and tail in ns:
                v = ns[tail]
                return bool(v) if isinstance(v, (bool, int)) else None
        return None

    async def _db_lookup(
        self,
        flag_key: str,
        company_id: Optional[UUID],
        entity_id: Optional[UUID] = None,
    ) -> Optional[_Resolution]:
        """Query the ``feature_flags`` table.

        Safe-degraded: if the table doesn't exist (migration hasn't
        run yet), the lookup returns None and the resolver falls
        through to env + defaults. Any other SQL exception is logged
        and treated as a miss so flags never break the worker.

        Priority: per-entity → per-company → global.
        """
        try:
            from sqlalchemy import text
            if entity_id is not None:
                row = (await self.db.execute(
                    text(
                        "SELECT enabled FROM feature_flags "
                        "WHERE flag_key = :k AND entity_id = :e"
                    ),
                    {"k": flag_key, "e": str(entity_id)},
                    bind_arguments=_on_control_plane(),
                )).first()
                if row is not None:
                    return _Resolution(
                        value=bool(row[0]),
                        source="entity_row",
                        flag_key=flag_key,
                    )
            # Per-company row — must have entity_id IS NULL so a
            # per-entity override never bleeds into the company tier.
            if company_id is not None:
                row = (await self.db.execute(
                    text(
                        "SELECT enabled FROM feature_flags "
                        "WHERE flag_key = :k AND company_id = :c "
                        "AND entity_id IS NULL"
                    ),
                    {"k": flag_key, "c": str(company_id)},
                    bind_arguments=_on_control_plane(),
                )).first()
                if row is not None:
                    return _Resolution(
                        value=bool(row[0]),
                        source="company",
                        flag_key=flag_key,
                    )
            # Global row.
            row = (await self.db.execute(
                text(
                    "SELECT enabled FROM feature_flags "
                    "WHERE flag_key = :k "
                    "AND company_id IS NULL AND entity_id IS NULL"
                ),
                {"k": flag_key},
                bind_arguments=_on_control_plane(),
            )).first()
            if row is not None:
                return _Resolution(
                    value=bool(row[0]),
                    source="global",
                    flag_key=flag_key,
                )
            return None
        except Exception as exc:                                           # pragma: no cover
            # A swallowed error here silently downgrades the flag to its
            # default even though an override row exists. Log at WARNING so that
            # fallback is never invisible.
            logger.warning(
                "feature_flags DB lookup failed for %s (%s); "
                "falling back to env/default",
                flag_key, type(exc).__name__,
            )
            return None


async def warn_if_table_missing() -> bool:
    """Log once, at startup, when the ``feature_flags`` table is absent (DM-03).

    Every lookup still falls back to env vars and code defaults — flags must
    never break a request — but a database without the table otherwise behaves
    exactly like one where every flag is at its default. Returns whether the
    table is there.
    """
    from sqlalchemy import text

    from src.common.tenancy.session import control_session

    try:
        async with control_session() as db:
            present = bool((await db.execute(text("SELECT to_regclass('public.feature_flags') IS NOT NULL"))).scalar())
    except Exception as exc:
        logger.warning("feature_flags: could not check for the table (%s)", type(exc).__name__)
        return False
    if not present:
        logger.warning(
            "feature_flags table is missing: every flag resolves from env vars and code "
            "defaults until migration p11t02_feature_flags runs"
        )
    return present

