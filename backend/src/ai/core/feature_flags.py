"""
ai.core.feature_flags — Phase 11 feature-flag service.

Resolution order (first hit wins):

  1. Per-entity override (``entity.metadata_extensions.feature_flags``).
  2. Per-company row in the ``feature_flags`` table.
  3. Global row (``company_id IS NULL``) in the ``feature_flags`` table.
  4. Environment variable: ``AI_FLAG_<KEY>`` (e.g.
     ``AI_FLAG_AGENT_LOOP_ENABLED=true``).
  5. Hard-coded default from ``DEFAULTS`` below.

Track 13 owns the formal admin-UI + audit-log story. This module is the
minimum viable plumbing the AgentLoop needs in Track 2.

The DB table is OPTIONAL — if Alembic hasn't run the migration yet,
flags fall through to env vars + defaults instead of raising. That
makes the system safe to deploy in any order.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Defaults — the source of truth when no DB / env override exists.
# Per Track 2 plan §8.
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, bool] = {
    # The AgentLoop is the sole run engine (C4 deleted the legacy
    # ExecutionEngine.execute_run path), so the ``agent_loop.enabled`` master
    # switch no longer exists. The remaining ``agent_loop.*`` flags tune
    # behaviour WITHIN the loop.
    "agent_loop.perception_bounded_viewport": True,
    "agent_loop.snapshot_every_iteration": True,
    "agent_loop.executor_dialog_enabled": False,
    "agent_loop.executor_skill_enabled": False,
    "agent_loop.executor_tool_burst_enabled": False,
    # Budget-aware REACT (Phase 12 `07` §2): thread budget pressure into the
    # step prompt as a soft constraint, with an explicit "finish, don't expand"
    # directive past ``agent_loop.budget_pressure_threshold``. The hard engine
    # cap still applies; this nudges the LLM to plan within budget. Default ON.
    "agent_loop.budget_aware_react": True,
    # Meta-Agent board is the default routing path (see the canonical entry
    # below; this alias kept ON for consistency).
    "meta_agent.board_routing": True,
    # Critic pipeline v2 defaults.
    "critic_pipeline.v2_enabled": True,
    "critic_pipeline.different_model_critic": True,
    "critic_pipeline.pre_critic_enabled": True,
    # (C1: critic_pipeline.v1_compat retired — the v1 critic body is deleted.)
    "critic_pipeline.calibration_enabled": True,
    # Legacy alias retained for tests / pre-Track-3 callers.
    "critic_pipeline.enabled": False,
    # Supervisor v2 + bandit defaults.
    "meta_review.v2_enabled": True,
    "meta_review.fast_path_enabled": True,
    "bandit.enabled": True,
    "task_classifier.v2_enabled": False,
    # Meta-Agent Board defaults.
    # `board_routing` defaults ON in this pre-production/development build
    # (30-day canary gate skipped); the board is the default Meta-Agent path.
    # Downstream gates already default ON so the master flip wires up cleanly.
    "meta_agent.board_routing": True,
    "meta_agent.spec_critic_required": True,
    "meta_agent.draft_lifecycle": True,
    "meta_agent.testdriver_suite_enabled": True,
    "meta_agent.skill_promotion_cron": True,
    "meta_agent.prompt_evolution_cron": True,
    "meta_agent.curator_consolidation_enabled": False,
    # Third-model tiebreak for high-stakes spec-critic disagreements (Phase 12
    # `06` §4.3). Default OFF; enabled per company.
    "meta_agent.spec_critic_tiebreak": False,
    # Tool synthesis kill switch (Phase 12 `06` §2.2 control 5). Default OFF;
    # the marquee/most-dangerous capability. Even when ON, the tool_synthesis
    # meta-tool stays Meta-Agent-only + container-only-exec + DRAFT-register-only.
    "meta_agent.tool_synthesis_enabled": False,
    # Tool & cost consolidation defaults.
    "tools.cost_resolver_v2_enabled": True,
    "tools.resilience_v2_enabled": True,
    # Last canary flag of the cost-attribution programme: flipped ON once
    # embedding became the final metered cost site (memory/embedding_service.py).
    # Every cost surface now writes an attributed usage_logs row; the CI guard
    # in tests/integration/test_cost_attribution.py enforces the invariant.
    "tools.cost_attribution_required": True,
    # Planner v2 defaults.
    "planner.v2_enabled": True,
    "planner.invariants_enforced": True,
    "planner.judge_enabled": True,
    "planner.priors_enabled": True,
    # Per-tenant container sandbox canary (Phase 12 `02` S4). Default ON
    # (globally enabled as of Phase 12 go-live — Step 1.3 of phase12_ops_guide.md).
    # A global DB row (company_id IS NULL) also enforces this; the code default
    # ensures the flag is True even on fresh installs before the DB row is present.
    "sandbox.container_runtime_enabled": True,
    # Per-tenant persistent browser profile canary (Phase 12 `02` S5). Default
    # OFF (ephemeral context). Resolved per-company and threaded into the tool
    # context as ``persistent_browser``; master is
    # settings.SANDBOX_PERSISTENT_BROWSER_ENABLED.
    "sandbox.persistent_browser_enabled": False,
    # Memory v2 canonicalisation defaults.
    "memory.v2_canonical": True,
    "memory.viewport_compact": True,
    "memory.scope_policy_enforced": True,
    "memory.dreaming_outcome_trigger": True,
    "memory.embedding_resolver_v2": True,
    # In-tenant provenance trust-score learning (Phase 12 `07` §3). Default OFF;
    # when ON, source outcomes are folded into a learned per-source trust score
    # the planner/critic can weight evidence by.
    "memory.trust_score_learning": False,
    # IntelligenceTree rule lifecycle (Phase 12 `06` §5): when ON, only
    # `confirmed` rules (candidate→confirmed→retired) enter planner/critic
    # prompts. Retired rules are always dropped; default OFF keeps legacy
    # (lifecycle-less) rules eligible so enabling never blanks prompts.
    "memory.rule_lifecycle_confirmed_only": False,
    # Legacy alias kept for any pre-Track-6 code paths.
    "memory_v2.canonical": True,
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
    "critic_pipeline.budget_share_cap": 0.20,
    # Meta-Agent test driver suite budget (USD).
    "meta_agent.testdriver_budget_usd": 3.00,
    # Planner candidate count.
    "planner.n_candidates": 3,
}


def _env_lookup(key: str) -> Optional[bool]:
    env_key = "AI_FLAG_" + key.upper().replace(".", "_")
    raw = os.environ.get(env_key)
    if raw is None:
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class _Resolution:
    value: bool
    source: str           # "entity", "company", "global", "env", "default"
    flag_key: str


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
        → global ``value_json`` → ``NUMERIC_DEFAULTS[flag_key]`` →
        ``default`` (caller fallback, 0.0 if not given).
        """
        if self.db is not None:
            for c_id, e_id in self._db_scope_chain(company_id, entity_id):
                val = await self._db_lookup_value_json(flag_key, c_id, e_id)
                if val is None:
                    continue
                try:
                    return float(val)
                except (TypeError, ValueError):
                    continue
        if flag_key in NUMERIC_DEFAULTS:
            return float(NUMERIC_DEFAULTS[flag_key])
        return float(default if default is not None else 0.0)

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
        )
        invalidate_process_cache(flag_key)
        await self._publish_invalidation(flag_key, company_id, entity_id)

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
        )
        affected = (result.rowcount or 0) > 0
        if affected:
            invalidate_process_cache(flag_key)
            await self._publish_invalidation(flag_key, company_id, entity_id)
        return affected

    async def _publish_invalidation(
        self,
        flag_key: str,
        company_id: Optional[UUID],
        entity_id: Optional[UUID],
    ) -> None:
        if self.redis is None:
            return
        try:
            import json as _json
            payload = _json.dumps({
                "flag_key": flag_key,
                "company_id": str(company_id) if company_id else None,
                "entity_id": str(entity_id) if entity_id else None,
            })
            await self.redis.publish(_REDIS_INVALIDATION_CHANNEL, payload)
        except Exception as exc:                                              # pragma: no cover
            logger.debug("feature_flag invalidation publish failed: %s", exc)

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
