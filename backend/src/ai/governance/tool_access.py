"""governance/tool_access.py — the one decision on whether a tool may run (P3.1).

Every execution and advertisement path resolves tools here, never in
``ToolRegistry`` directly. A tool runs for an entity when:

* the entity is granted it (``capabilities.tools``) or the platform injects it
  (the meta-cognition tools, ``resolve_meta_cognition``) — TL-50;
* the model asked for it and the grant lets the model call it (``PLANNED``
  tools run only from a plan step) — TL-12 / TX-03;
* no admin has switched it off (``tool_registry_entries.is_enabled``) — TL-14;
* it is ``ACTIVE``/``DEPRECATED``, or the company opted in to it with
  ``tools.experimental.<name>`` (``EXPERIMENTAL``/``DRAFT``) — TL-13.

The company's own (tenant) tools resolve before the platform's — TL-10.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel

from src.ai.schemas.capabilities import ToolGrant
from src.ai.tools.base import Tool, ToolRegistry, ToolStatus

logger = logging.getLogger(__name__)

__all__ = ["ToolGrant", "ToolDenied", "ToolAccess", "Via", "grants_of", "injected_meta_tools"]

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
    reason: str      # not_granted | not_llm_callable | not_plan_callable | disabled | opt_in_required | not_registered
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

    @classmethod
    async def load(
        cls,
        db: Any,
        company_id: Optional[UUID],
        entity: Any,
        *,
        meta_tools: bool = True,
        feature_flags: Any = None,
    ) -> "ToolAccess":
        """Read the entity's grants, the admin kill switches and the company's
        opt-ins once; resolution after that is in memory."""
        grants = grants_of(entity)
        injected = frozenset(injected_meta_tools(entity)) if meta_tools else frozenset()
        cid = _as_uuid(company_id)
        disabled = await _disabled_names(db, cid)
        opted_in = await _opted_in(db, cid, [*grants, *injected], feature_flags)
        return cls(
            company_id=cid, grants=grants, injected=injected, disabled=disabled,
            opted_in=opted_in, entity_name=str(getattr(entity, "name", "") or ""),
        )

    # ------------------------------------------------------------------

    def resolve(self, name: str, via: Via = "llm") -> Union[Tool, ToolDenied]:
        """The tool ``name`` if it may run here, else why not."""
        name = str(name or "")
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
            tool = self.resolve(name, "llm")
            if isinstance(tool, Tool):
                out.append(tool.get_function_schema())
        return out

    def schema_for(self, name: str) -> Optional[dict[str, Any]]:
        tool = self.resolve(name, "plan") if name in self.grants else self.resolve(name, "llm")
        return tool.get_function_schema() if isinstance(tool, Tool) else None

    def grant(self, name: str) -> Optional[ToolGrant]:
        return self.grants.get(name)

    def _deny(self, name: str, reason: str, why: str) -> ToolDenied:
        granted = ", ".join(self.llm_tool_ids()) or "none"
        _event("agent.tool.denied", tool_id=name, reason=reason,
               company_id=str(self.company_id), entity=self.entity_name)
        return ToolDenied(
            tool=name, reason=reason,
            message=f"Error: tool '{name}' {why}. Tools available to you: {granted}.",
        )


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
