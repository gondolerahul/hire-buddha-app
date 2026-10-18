"""governance/tool_access.py — the one decision on whether a tool may run (P3.1).

Every execution and advertisement path resolves tools here, never in
``ToolRegistry`` directly. A tool runs for an entity when:

* the entity is granted it (``capabilities.tools``) or the platform injects it
  (the meta-cognition tools, ``resolve_meta_cognition``) — TL-50;
* the model asked for it and the grant lets the model call it (``PLANNED``
  tools run only from a plan step) — TL-12 / TX-03;
* no admin has switched it off (``tool_registry_entries.is_enabled``) — TL-14;
* it is ``ACTIVE``/``DEPRECATED``, or the company opted in to it with
  ``tools.experimental.<name>`` (``EXPERIMENTAL``/``DRAFT``) — TL-13;
* the run has calls left: the grant's ``rate_limit_per_run``, the entity's
  ``governance.execution_limits.max_tool_calls``, and for an entity that is not
  the Meta-Agent ``meta_cognition.max_runtime_creations`` on
  ``meta_entity_creator`` — TL-11, TL-21. A run's calls are its
  ``tool_interaction_logs`` rows, so the count survives steps, suspends and
  workers.

The company's own (tenant) tools resolve before the platform's — TL-10.

What a tool is told about its call — company, user, run, entity — is an
:class:`ExecutionContext` the platform builds (P3.2). Run input never reaches it
(TL-53), so a caller cannot choose the tenant, the meta-agent gate (TL-65) or a
runtime knob through ``input_data``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Mapping, Optional, Union
from uuid import UUID

from pydantic import BaseModel

from src.ai.schemas.capabilities import ToolGrant
from src.ai.tools.base import Tool, ToolRegistry, ToolStatus

logger = logging.getLogger(__name__)

__all__ = [
    "ToolGrant", "ToolDenied", "ToolAccess", "Via", "grants_of", "injected_meta_tools",
    "ExecutionContext", "LOOP_STATE_KEYS",
]

# Loop-owned state a tool may read (the introspection and reflection tools).
# The loop writes these into the run's context; run input cannot (see
# ``schemas.execution.RESERVED_INPUT_KEYS``), so passing them on does not pass
# the caller's data on.
LOOP_STATE_KEYS: tuple[str, ...] = (
    "__agent_state__", "__execution_metadata__", "__cortex_tree_id__", "__cortex_cursor__",
)

Via = Literal["llm", "plan"]


def grants_of(entity: Any) -> dict[str, ToolGrant]:
    """The entity's tool grants by tool id. An unreadable entry grants nothing."""
    caps: Any = getattr(entity, "capabilities", None)
    if caps is None and isinstance(entity, dict):
        caps = entity.get("capabilities")
    if isinstance(caps, BaseModel):
        caps = caps.model_dump()
    out: dict[str, ToolGrant] = {}
    for raw in (caps or {}).get("tools") or []:
        try:
            grant = ToolGrant.model_validate(raw)
        except Exception:                                   # noqa: BLE001 - a bad entry grants nothing
            logger.warning("Ignoring unreadable tool grant %r", raw)
            continue
        if grant.tool_id:
            out[grant.tool_id] = grant
    return out


def injected_meta_tools(entity: Any) -> list[str]:
    """The meta-cognition tools the platform gives this entity."""
    from src.ai.meta.platform_schema_compiler import resolve_meta_cognition
    meta = resolve_meta_cognition(entity)
    names: list[str] = []
    if meta.get("registry_search"):
        names.append("meta_registry_search")
    if meta.get("self_modification"):
        names += ["meta_entity_creator", "meta_entity_executor"]
    if meta.get("self_introspection"):
        names.append("agent_introspect")
    if meta.get("reflection"):
        names.append("agent_reflect")
    return names


@dataclass(frozen=True)
class ToolDenied:
    """Why a tool may not run here. ``message`` is what the model reads."""
    tool: str
    reason: str      # not_granted | not_llm_callable | not_plan_callable | disabled | not_registered
                     # | opt_in_required | call_budget | rate_limited
    message: str


@dataclass(frozen=True)
class ToolAccess:
    """What one entity may run, for one company. Build with :meth:`load`."""
    company_id: Optional[UUID]
    grants: dict[str, ToolGrant] = field(default_factory=dict)
    injected: frozenset[str] = frozenset()
    disabled: frozenset[str] = frozenset()
    opted_in: frozenset[str] = frozenset()
    entity_name: str = ""
    # Per-run limits (P3.3). ``used`` is the run's calls so far by tool; it is
    # read from the run's logs on load and advanced by :meth:`record`.
    max_tool_calls: Optional[int] = None
    creation_limit: Optional[int] = None
    used: dict[str, int] = field(default_factory=dict)
    # What each tool's declaration says for this business and entity
    # (``Tool.tailoring``; the record tools' objects and fields, WS4 4.8).
    tailoring: dict[str, Any] = field(default_factory=dict)

    @classmethod
    async def load(
        cls,
        db: Any,
        company_id: Optional[UUID],
        entity: Any,
        *,
        meta_tools: bool = True,
        feature_flags: Any = None,
        run_id: Any = None,
    ) -> "ToolAccess":
        """Read the entity's grants, the admin kill switches, the company's
        opt-ins and the run's calls so far once; resolution after that is in
        memory."""
        grants = grants_of(entity)
        injected = frozenset(injected_meta_tools(entity)) if meta_tools else frozenset()
        cid = _as_uuid(company_id)
        disabled = await _disabled_names(db, cid)
        opted_in = await _opted_in(db, cid, [*grants, *injected], feature_flags)
        is_meta_agent = bool(_meta_extensions(entity).get("is_meta_agent"))
        return cls(
            company_id=cid, grants=grants, injected=injected, disabled=disabled,
            opted_in=opted_in, entity_name=str(getattr(entity, "name", "") or ""),
            max_tool_calls=_max_tool_calls(entity),
            creation_limit=None if is_meta_agent else _max_runtime_creations(entity),
            used=await _calls_so_far(db, _as_uuid(run_id)),
            tailoring=await _tailoring(cid, entity, [*grants, *injected]),
        )

    # ------------------------------------------------------------------

    def timeout_for(self, name: str, tool: Tool) -> float:
        """How long one call of ``tool`` may run: the grant's, else the tool's (EP-08)."""
        grant = self.grants.get(str(name or ""))
        return float(getattr(grant, "timeout_seconds", None) or tool.timeout_seconds)

    def resolve(self, name: str, via: Via = "llm") -> Union[Tool, ToolDenied]:
        """The tool ``name`` if it may run here, else why not."""
        out = self._check(str(name or ""), via)
        if isinstance(out, ToolDenied):
            _event("agent.tool.denied", tool_id=out.tool, reason=out.reason,
                   company_id=str(self.company_id), entity=self.entity_name)
        return out

    def record(self, name: str) -> None:
        """Count one call that ran (a fallback ``a→b`` counts for both)."""
        for part in str(name or "").split("→"):
            if part:
                self.used[part] = self.used.get(part, 0) + 1

    def calls_left(self) -> Optional[int]:
        """Calls the run may still make under ``max_tool_calls`` (None: no cap)."""
        if self.max_tool_calls is None:
            return None
        return max(self.max_tool_calls - sum(self.used.values()), 0)

    def _limit(self, name: str) -> Optional[int]:
        grant = self.grants.get(name)
        limits = [grant.rate_limit_per_run] if grant is not None else []
        if name == "meta_entity_creator":
            limits.append(self.creation_limit)
        found = [n for n in limits if n is not None]
        return min(found) if found else None

    def _check(self, name: str, via: Via) -> Union[Tool, ToolDenied]:
        grant = self.grants.get(name)
        if grant is None and name not in self.injected:
            return self._deny(name, "not_granted", "is not granted to this entity")
        if grant is not None and via == "llm" and not grant.llm_callable and name not in self.injected:
            return self._deny(name, "not_llm_callable", "runs only from a plan step, not on the model's request")
        if grant is not None and via == "plan" and not grant.plan_callable:
            return self._deny(name, "not_plan_callable", "may not be run from a plan step")
        if name in self.disabled:
            return self._deny(name, "disabled", "is switched off by an administrator")
        tool = ToolRegistry.get_tool(name, company_id=self.company_id)
        if tool is None:
            return self._deny(name, "not_registered", "is not installed on this platform")
        status = getattr(tool, "status", ToolStatus.ACTIVE)
        if status in (ToolStatus.EXPERIMENTAL, ToolStatus.DRAFT) and name not in self.opted_in:
            return self._deny(
                name, "opt_in_required",
                f"is {status.value} and this company has not opted in (tools.experimental.{name})",
            )
        if self.calls_left() == 0:
            return self._deny(name, "call_budget",
                              f"may not run: this run used all {self.max_tool_calls} of its tool calls")
        limit = self._limit(name)
        if limit is not None and self.used.get(name, 0) >= limit:
            return self._deny(name, "rate_limited",
                              f"may not run again: it may be called {limit} time(s) per run")
        if status == ToolStatus.DEPRECATED:
            _event("agent.tool.deprecated_call", tool_id=name, company_id=str(self.company_id))
        return tool

    def llm_tool_ids(self) -> list[str]:
        """The tools the model is offered: granted for the model, then injected."""
        ids = [n for n, g in self.grants.items() if g.llm_callable]
        ids += [n for n in sorted(self.injected) if n not in ids]
        return ids

    def schemas(self) -> list[dict[str, Any]]:
        """Function schemas of every tool the model may call here — the same
        rule as :meth:`resolve`, so nothing is advertised that would be refused."""
        out = []
        for name in self.llm_tool_ids():
            tool = self._check(name, "llm")
            if isinstance(tool, Tool):
                schema = tool.function_schema_for(self.tailoring.get(name))
                if schema is not None:
                    out.append(schema)
        return out

    def schema_for(self, name: str) -> Optional[dict[str, Any]]:
        tool = self._check(name, "plan" if name in self.grants else "llm")
        return tool.function_schema_for(self.tailoring.get(name)) if isinstance(tool, Tool) else None

    def grant(self, name: str) -> Optional[ToolGrant]:
        return self.grants.get(name)

    def _deny(self, name: str, reason: str, why: str) -> ToolDenied:
        granted = ", ".join(self.llm_tool_ids()) or "none"
        return ToolDenied(
            tool=name, reason=reason,
            message=f"Error: tool '{name}' {why}. Tools available to you: {granted}.",
        )


@dataclass(frozen=True)
class ExecutionContext:
    """What a tool is told about its call, built by the platform (P3.2).

    Tools read tenancy, identity and the meta-agent gate from here and nowhere
    else — never from their own parameters (TL-03) or from run input (TL-53).
    Each call gets a fresh dict from :meth:`as_tool_context`, so a tool that
    writes to its context changes nothing for the next call.
    """
    company_id: str
    user_id: Optional[str] = None
    run_id: Optional[str] = None
    agent_id: Optional[str] = None
    entity_name: str = ""
    is_meta_agent: bool = False
    max_runtime_creations: int = 3
    campaign_id: Optional[str] = None
    # The entity lets its tools take raw recipients (``to``, ``phone``…) rather
    # than refs from the run's subject scope (TL-09, P6.11). Off by default.
    allow_free_recipients: bool = False
    loop_state: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def for_run(
        cls, run: Any, entity: Any, run_context: Optional[Mapping[str, Any]] = None,
    ) -> "ExecutionContext":
        """The context of a tool call inside ``run``, for ``entity``."""
        meta = _meta_extensions(entity)
        state = run_context or {}
        return cls(
            company_id=str(run.company_id),
            user_id=str(run.user_id) if getattr(run, "user_id", None) else None,
            run_id=str(run.id),
            agent_id=str(entity.id) if getattr(entity, "id", None) is not None else None,
            entity_name=str(getattr(entity, "name", "") or ""),
            is_meta_agent=bool(meta.get("is_meta_agent")),
            max_runtime_creations=_max_runtime_creations(entity),
            allow_free_recipients=_allow_free_recipients(entity),
            loop_state=_loop_state(state),
        )

    @classmethod
    def for_session(
        cls, company_id: Any, entity: Any, *, user_id: Any = None, campaign_id: Any = None,
        run_id: Any = None,
    ) -> "ExecutionContext":
        """The context of a tool call in a live session (voice); ``run_id`` is
        the run the session's tool calls are logged and charged to (TL-20)."""
        return cls(
            company_id=str(company_id),
            user_id=str(user_id) if user_id else None,
            run_id=str(run_id) if run_id else None,
            agent_id=str(entity.id) if getattr(entity, "id", None) is not None else None,
            entity_name=str(getattr(entity, "name", "") or ""),
            is_meta_agent=bool(_meta_extensions(entity).get("is_meta_agent")),
            campaign_id=str(campaign_id) if campaign_id else None,
            allow_free_recipients=_allow_free_recipients(entity),
        )

    def as_tool_context(self) -> dict[str, Any]:
        ctx: dict[str, Any] = {
            "company_id": self.company_id,
            "user_id": self.user_id or "default",
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "entity_id": self.agent_id,
            "__entity_id__": self.agent_id,
            "__entity_name__": self.entity_name,
            "__is_meta_agent__": self.is_meta_agent,
            "__meta_max_runtime_creations__": self.max_runtime_creations,
            "campaign_id": self.campaign_id,
            "__allow_free_recipients__": self.allow_free_recipients,
        }
        ctx.update(self.loop_state)
        return ctx


async def _tailoring(company_id: Optional[UUID], entity: Any, names: Iterable[str]) -> dict[str, Any]:
    """Each tool's ``tailoring`` for this business and entity; a tool whose
    tailoring fails keeps its plain declaration (it is logged)."""
    out: dict[str, Any] = {}
    shared: dict[str, Any] = {}
    for name in dict.fromkeys(names):
        tool = ToolRegistry.get_tool(name, company_id=company_id)
        if not isinstance(tool, Tool) or type(tool).tailoring is Tool.tailoring:
            continue
        try:
            value = await tool.tailoring(company_id, entity, shared)
        except Exception as error:                          # noqa: BLE001 - a declaration is never fatal
            logger.warning("Tool %s: no per-business declaration (%s)", name, error)
            continue
        if value is not None:
            out[name] = value
    return out


def _meta_extensions(entity: Any) -> Mapping[str, Any]:
    meta = getattr(entity, "metadata_extensions", None)
    return meta if isinstance(meta, Mapping) else {}


def _loop_state(context: Mapping[str, Any]) -> dict[str, Any]:
    """Loop-owned state a tool may read: the run context's loop keys, and the
    ``__agent_state__`` view of the loop's typed signals (AK-21)."""
    out = {k: context[k] for k in LOOP_STATE_KEYS if k in context}
    from src.ai.core.step_signals import current_signals
    signals = current_signals()
    if signals is not None:
        out["__agent_state__"] = signals.agent_state()
    return out


def _allow_free_recipients(entity: Any) -> bool:
    gov = getattr(entity, "governance", None)
    return isinstance(gov, Mapping) and gov.get("allow_free_recipients") is True


def _max_tool_calls(entity: Any) -> Optional[int]:
    gov = getattr(entity, "governance", None)
    limits = gov.get("execution_limits") if isinstance(gov, Mapping) else None
    value = limits.get("max_tool_calls") if isinstance(limits, Mapping) else None
    return value if isinstance(value, int) and value > 0 else None


def _max_runtime_creations(entity: Any) -> int:
    caps = getattr(entity, "capabilities", None)
    meta = (caps or {}).get("meta_cognition") if isinstance(caps, Mapping) else None
    value = meta.get("max_runtime_creations") if isinstance(meta, Mapping) else None
    return int(value) if isinstance(value, int) else 3


# ---------------------------------------------------------------------------


def _as_uuid(value: Any) -> Optional[UUID]:
    if value is None or isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


async def _disabled_names(db: Any, company_id: Optional[UUID]) -> frozenset[str]:
    """Names an admin switched off: platform rows, and this company's rows."""
    if db is None:
        return frozenset()
    from sqlalchemy import ColumnElement, or_, select
    from src.ai.orm.tools import ToolRegistryEntry
    scope: list[ColumnElement[bool]] = [ToolRegistryEntry.company_id.is_(None)]
    if company_id is not None:
        scope.append(ToolRegistryEntry.company_id == company_id)
    rows = await db.execute(
        select(ToolRegistryEntry.name).where(
            ToolRegistryEntry.is_enabled.is_(False), or_(*scope),
        )
    )
    return frozenset(rows.scalars().all())


async def _calls_so_far(db: Any, run_id: Optional[UUID]) -> dict[str, int]:
    """The run's tool calls so far by tool: its log rows, less refused calls
    and replays of a write the run had already made (TL-39)."""
    if db is None or run_id is None:
        return {}
    from sqlalchemy import func, select
    from src.ai.orm.execution import ToolInteractionLog
    rows = await db.execute(
        select(ToolInteractionLog.tool_id, func.count()).where(
            ToolInteractionLog.run_id == run_id,
            ToolInteractionLog.log_metadata["refused"].astext.is_(None),
            ToolInteractionLog.log_metadata["replayed"].astext.is_(None),
        ).group_by(ToolInteractionLog.tool_id)
    )
    used: dict[str, int] = {}
    for tool_id, n in rows.all():
        for part in str(tool_id).split("→"):
            used[part] = used.get(part, 0) + int(n)
    return used


async def _opted_in(
    db: Any, company_id: Optional[UUID], names: Iterable[str], feature_flags: Any,
) -> frozenset[str]:
    """Which of ``names`` need an opt-in and have it for this company."""
    need = []
    for name in dict.fromkeys(names):
        tool = ToolRegistry.get_tool(name, company_id=company_id)
        if tool is not None and getattr(tool, "status", None) in (ToolStatus.EXPERIMENTAL, ToolStatus.DRAFT):
            need.append(name)
    if not need:
        return frozenset()
    if feature_flags is None:
        from src.ai.core.feature_flags import FeatureFlags
        feature_flags = FeatureFlags(db)
    on = set()
    for name in need:
        if await feature_flags.is_on(f"tools.experimental.{name}", company_id=company_id):
            on.add(name)
    return frozenset(on)


def _event(name: str, **payload: Any) -> None:
    try:
        from src.ai.core.events import event
        event(name, **payload)
    except Exception:                                        # pragma: no cover - telemetry is best-effort
        pass
