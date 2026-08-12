"""
ai.planning.child_resolver — Phase 11 Track 7 single-source-of-truth
for ``CHILD_ENTITY_INVOCATION.entity_id`` resolution.

Both :class:`ai.planning.planner_service.PlannerService` and
:class:`ai.step_executor.StepExecutorService` historically resolved
dropped/renamed child ``entity_id`` inline, with four overlapping
strategies that drifted over time. Track 7 consolidates them here as
one async function the two call sites delegate to.

Strategies tried, in order:

  1. **UUID passthrough** — ``step.target.entity_id`` is already a UUID
     (object or string) and parses cleanly.
  2. **Static-plan name match** — find a ``CHILD_ENTITY_INVOCATION``
     step in ``entity.planning.static_plan.steps`` whose ``name``
     case-insensitively matches ``step.name`` (exact, then substring).
  3. **Hierarchy index match** — count this step's position among
     ``CHILD_ENTITY_INVOCATION`` steps in the static plan, then look
     up the matching entry in ``entity.hierarchy.children[]``.
  4. **Entity-name-hint DB lookup** — fall back to a DB query against
     ``HierarchicalEntity.name`` using ``step.target.entity_name_hint``.

If none resolve, :class:`EntityNotFoundError` is raised. Each
successful resolution emits an ``agent.child_resolver.fallback`` event
(strategy index 1-4); a final miss emits
``agent.child_resolver.failed``.
"""
from __future__ import annotations

import logging
from typing import Any, Optional, Union, cast
from uuid import UUID

logger = logging.getLogger(__name__)

__all__ = ["resolve_child_entity_id", "EntityNotFoundError"]


class EntityNotFoundError(LookupError):
    """Raised when no strategy can resolve a CHILD_ENTITY_INVOCATION's entity_id."""

    def __init__(self, step_name: str, parent_entity_id: Optional[Any]):
        super().__init__(
            f"ChildResolver: could not resolve entity_id for step '{step_name}' "
            f"(parent_entity_id={parent_entity_id})"
        )
        self.step_name = step_name
        self.parent_entity_id = parent_entity_id


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def resolve_child_entity_id(
    step: Any,
    parent_entity: Any,
    db: Any = None,
    *,
    emit_event: Any = None,
) -> UUID:
    """Resolve the ``entity_id`` of a CHILD_ENTITY_INVOCATION step.

    Args:
        step: A :class:`PlanStep` (or dict shaped like one).
        parent_entity: The parent :class:`HierarchicalEntity` driving the run.
        db: Async SQLAlchemy session — required only for Strategy 4.
        emit_event: Optional async callable ``(name: str, **payload) -> None``
            invoked on successful and failed resolution. Default: silent.

    Returns:
        UUID of the resolved child entity.

    Raises:
        EntityNotFoundError: When no strategy succeeds.
    """
    step_name = _step_name(step)
    parent_id = getattr(parent_entity, "id", None)

    # Strategy 1 — UUID passthrough.
    raw_id = _read_target_entity_id(step)
    eid = _coerce_uuid(raw_id)
    if eid is not None:
        await _emit(emit_event, "agent.child_resolver.fallback",
                    strategy_used=1, step_name=step_name)
        return eid

    # Strategies 2 & 3 — derive from parent's static plan + hierarchy.
    static_steps = _static_invocation_steps(parent_entity)

    # Strategy 2 — static-plan name match (exact then substring).
    matched = _match_by_name(static_steps, step_name)
    if matched is not None:
        eid = _coerce_uuid((matched.get("target") or {}).get("entity_id"))
        if eid is not None:
            await _emit(emit_event, "agent.child_resolver.fallback",
                        strategy_used=2, step_name=step_name)
            return eid

    # Strategy 3 — hierarchy index match.
    children = _hierarchy_children(parent_entity)
    if static_steps and children:
        for idx, ss in enumerate(static_steps):
            ss_name = str(ss.get("name", "")).strip().lower()
            if ss_name and ss_name == step_name.strip().lower() and idx < len(children):
                child_eid = _coerce_uuid(children[idx].get("child_id"))
                if child_eid is not None:
                    await _emit(emit_event, "agent.child_resolver.fallback",
                                strategy_used=3, step_name=step_name)
                    return child_eid

    # Strategy 4 — entity_name_hint DB lookup.
    name_hint = _read_name_hint(step)
    if name_hint and db is not None:
        from sqlalchemy import select
        from src.ai.orm.entity import HierarchicalEntity
        try:
            row = (await db.execute(
                select(HierarchicalEntity).where(
                    HierarchicalEntity.name == name_hint,
                    HierarchicalEntity.status != "DELETED",
                )
            )).scalar_one_or_none()
            if row is not None:
                await _emit(emit_event, "agent.child_resolver.fallback",
                            strategy_used=4, step_name=step_name)
                return cast(UUID, row.id)
        except Exception as exc:                                            # pragma: no cover
            logger.debug(f"ChildResolver Strategy 4 lookup failed: {exc}")

    await _emit(emit_event, "agent.child_resolver.failed",
                step_name=step_name, parent_entity_id=str(parent_id) if parent_id else None)
    raise EntityNotFoundError(step_name=step_name, parent_entity_id=parent_id)


# ---------------------------------------------------------------------------
# Helpers — kept tiny so the strategies above read like prose.
# ---------------------------------------------------------------------------


def _step_name(step: Any) -> str:
    if isinstance(step, dict):
        return str(step.get("name", ""))
    return str(getattr(step, "name", "")) or ""


def _read_target_entity_id(step: Any) -> Optional[Union[str, UUID]]:
    if isinstance(step, dict):
        target = step.get("target") or {}
        return target.get("entity_id")
    target = getattr(step, "target", None)
    return getattr(target, "entity_id", None)


def _read_name_hint(step: Any) -> Optional[str]:
    if isinstance(step, dict):
        target = step.get("target") or {}
        v = target.get("entity_name_hint")
        return str(v) if v else None
    target = getattr(step, "target", None)
    v = getattr(target, "entity_name_hint", None)
    return str(v) if v else None


def _coerce_uuid(raw: Any) -> Optional[UUID]:
    if raw is None or raw == "":
        return None
    if isinstance(raw, UUID):
        return raw
    try:
        return UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None


def _static_invocation_steps(parent_entity: Any) -> list[dict[str, Any]]:
    planning = getattr(parent_entity, "planning", None)
    if planning is None and isinstance(parent_entity, dict):
        planning = parent_entity.get("planning")
    planning = planning or {}
    steps = (planning.get("static_plan") or {}).get("steps") or []
    return [s for s in steps if isinstance(s, dict)
            and str(s.get("type", "")).upper() == "CHILD_ENTITY_INVOCATION"]


def _hierarchy_children(parent_entity: Any) -> list[dict[str, Any]]:
    h = getattr(parent_entity, "hierarchy", None)
    if h is None and isinstance(parent_entity, dict):
        h = parent_entity.get("hierarchy")
    h = h or {}
    return list(h.get("children") or [])


def _match_by_name(static_steps: list[dict[str, Any]], step_name: str) -> Optional[dict[str, Any]]:
    needle = (step_name or "").strip().lower()
    if not needle:
        return None
    # Exact match first.
    for ss in static_steps:
        if str(ss.get("name", "")).strip().lower() == needle:
            return ss
    # Substring fallback (LLM may have paraphrased).
    for ss in static_steps:
        ss_name = str(ss.get("name", "")).strip().lower()
        if ss_name and (ss_name in needle or needle in ss_name):
            return ss
    return None


async def _emit(emit_event: Any, name: str, **payload: Any) -> None:
    if emit_event is None:
        return
    try:
        await emit_event(name, **payload)
    except Exception:                                                       # pragma: no cover
        return
