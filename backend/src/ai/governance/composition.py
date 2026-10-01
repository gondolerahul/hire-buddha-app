"""
ai.governance.composition — the composition rule of the hierarchy (R1).

An entity names its children three ways:

* a child row's ``parent_id``;
* ``hierarchy.children[].child_id``;
* the target of a ``CHILD_ENTITY_INVOCATION`` step in ``planning.static_plan`` —
  an ``entity_id``, or an ``entity_name_hint`` the child resolver looks up by
  name inside the parent's company.

Every child exists and is not deleted, belongs to its parent's company, and sits
at its parent's level or below (``schemas.levels.can_parent``); the tree has no
cycle. Same-level children are allowed — a department federating
sub-departments, a process calling a sub-process, a skill reusing a skill.

The rule is checked in three places, so no path skips it:

1. **Authoring** — ``AIService.create_entity`` / ``update_entity`` (422):
   :func:`authoring_violations`. An unresolved reference is tolerated there —
   the seed scripts save ``__PLACEHOLDER__`` targets and patch them afterwards.
2. **Dispatch** — ``AIService.trigger_execution`` (400), over the whole tree:
   :func:`dispatch_violations`. Every invocation step must resolve here.
3. **Runtime** — ``StepExecutorService.create_child_run`` refuses the child run:
   :func:`runtime_violation`. A dynamic plan's children are first seen here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select

from src.ai.schemas.levels import can_parent

__all__ = [
    "EntityShape",
    "ChildReference",
    "ChildDepth",
    "DEFAULT_MAX_RECURSION_DEPTH",
    "child_references",
    "authoring_violations",
    "dispatch_violations",
    "runtime_violation",
    "max_recursion_depth",
    "child_depth",
    "DEFAULT_MAX_CONCURRENT_CHILDREN",
    "max_concurrent_children",
    "ENTITY_STATUS_TRANSITIONS",
    "status_transition_problem",
]

DEFAULT_MAX_RECURSION_DEPTH = 5
DEFAULT_MAX_CONCURRENT_CHILDREN = 8

CHILD_STEP = "CHILD_ENTITY_INVOCATION"


def _type_name(value: Any) -> str:
    return str(getattr(value, "value", value) or "").upper()


def _as_uuid(value: Any) -> Optional[UUID]:
    if value is None or value == "":
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


@dataclass(frozen=True)
class EntityShape:
    """What the rule reads of an entity: a stored row, or one about to be written."""

    id: Optional[UUID]
    type: str
    company_id: Optional[UUID]
    parent_id: Optional[UUID]
    hierarchy: Any
    planning: Any
    name: str = ""

    @classmethod
    def of(cls, entity: Any) -> "EntityShape":
        return cls(
            id=_as_uuid(getattr(entity, "id", None)),
            type=_type_name(getattr(entity, "type", "")),
            company_id=_as_uuid(getattr(entity, "company_id", None)),
            parent_id=_as_uuid(getattr(entity, "parent_id", None)),
            hierarchy=getattr(entity, "hierarchy", None),
            planning=getattr(entity, "planning", None),
            name=str(getattr(entity, "name", "") or ""),
        )

    def with_changes(self, data: dict[str, Any]) -> "EntityShape":
        """The shape after an update payload (``model_dump(mode="json")``) is applied."""
        return replace(
            self,
            type=_type_name(data["type"]) if "type" in data else self.type,
            parent_id=_as_uuid(data["parent_id"]) if "parent_id" in data else self.parent_id,
            hierarchy=data["hierarchy"] if "hierarchy" in data else self.hierarchy,
            planning=data["planning"] if "planning" in data else self.planning,
            name=str(data.get("name") or self.name),
        )


@dataclass(frozen=True)
class ChildReference:
    """One child an entity's own configuration names."""

    where: str                   # human-readable location, for messages
    entity_id: Optional[UUID]    # None when the target is a name or a placeholder
    raw: Any                     # what was written there
    step: Optional[dict[str, Any]] = None  # the invocation step, when it is one


def child_references(hierarchy: Any, planning: Any) -> list[ChildReference]:
    """The children named in ``hierarchy.children`` and in the static plan."""
    refs: list[ChildReference] = []
    children = (hierarchy or {}).get("children") if isinstance(hierarchy, dict) else None
    for i, ref in enumerate(children or []):
        if isinstance(ref, dict) and ref.get("child_id"):
            raw = ref.get("child_id")
            refs.append(ChildReference(f"hierarchy.children[{i}]", _as_uuid(raw), raw))
    static_plan = (planning or {}).get("static_plan") if isinstance(planning, dict) else None
    steps = (static_plan or {}).get("steps") if isinstance(static_plan, dict) else None
    for step in steps or []:
        if not isinstance(step, dict) or _type_name(step.get("type")) != CHILD_STEP:
            continue
        target = step.get("target") or {}
        raw = target.get("entity_id") or target.get("entity_name_hint")
        label = step.get("name") or step.get("step_id") or "?"
        refs.append(ChildReference(f"step '{label}'", _as_uuid(target.get("entity_id")), raw, step))
    return refs


async def _load(db: Any, entity_id: UUID, company_id: Optional[UUID]) -> Any:
    """The entity inside ``company_id``; ``None`` when missing, deleted or another tenant's."""
    from src.ai.orm.entity import HierarchicalEntity as HE

    if company_id is None:
        return None
    return (await db.execute(
        select(HE).where(HE.id == entity_id, HE.company_id == company_id)
    )).scalar_one_or_none()


async def _row_children(db: Any, entity_id: UUID, company_id: Optional[UUID]) -> list[Any]:
    """Rows whose ``parent_id`` is ``entity_id``, inside the company."""
    from src.ai.orm.entity import HierarchicalEntity as HE

    if company_id is None:
        return []
    return list((await db.execute(
        select(HE).where(HE.parent_id == entity_id, HE.company_id == company_id)
    )).scalars().all())


def _level_problem(where: str, parent_type: str, child: Any) -> Optional[str]:
    child_type = _type_name(child.type)
    try:
        allowed = can_parent(parent_type, child_type)
    except (KeyError, ValueError):
        return f"{where} names {child.name}, whose type {child_type!r} is not a level"
    if allowed:
        return None
    return (
        f"{where} names {child.name}, a {child_type}: a {parent_type} can only "
        f"compose entities at its own level or below"
    )


def _status_problem(where: str, parent: Any, child: Any) -> Optional[str]:
    """ARCHIVED never runs; a DRAFT runs on its own or inside a draft tree (EP-09)."""
    child_status = _type_name(getattr(child, "status", ""))
    if child_status == "ARCHIVED":
        return f"{where} names {child.name}, which is ARCHIVED and does not run"
    if child_status == "DRAFT" and _type_name(getattr(parent, "status", "")) != "DRAFT":
        return (
            f"{where} names {child.name}, a DRAFT: a draft runs on its own or inside "
            f"a draft tree, not under a published parent"
        )
    return None


async def authoring_violations(db: Any, shape: EntityShape) -> list[str]:
    """What is wrong with the entity as it is about to be written.

    Checks the parent edge and every child the configuration names by id;
    a name or placeholder target is left for dispatch. On an update
    (``shape.id`` set) also refuses an edit that closes a cycle.
    """
    problems: list[str] = []
    own_type = shape.type

    if shape.parent_id is not None:
        if shape.id is not None and shape.parent_id == shape.id:
            problems.append("an entity cannot be its own parent")
        else:
            parent = await _load(db, shape.parent_id, shape.company_id)
            if parent is None:
                problems.append(f"parent {shape.parent_id} does not exist in this company")
            else:
                parent_type = _type_name(parent.type)
                try:
                    ok = can_parent(parent_type, own_type)
                except (KeyError, ValueError):
                    ok = True   # an unknown stored type is the read path's concern
                if not ok:
                    problems.append(
                        f"a {own_type} cannot sit under {parent.name}, a {parent_type}: "
                        f"a child sits at its parent's level or below"
                    )

    named: list[UUID] = []
    for ref in child_references(shape.hierarchy, shape.planning):
        if ref.entity_id is None:
            continue
        if shape.id is not None and ref.entity_id == shape.id:
            problems.append(f"{ref.where} names the entity itself")
            continue
        child = await _load(db, ref.entity_id, shape.company_id)
        if child is None:
            problems.append(f"{ref.where} names {ref.entity_id}, which does not exist in this company")
            continue
        level = _level_problem(ref.where, own_type, child)
        if level:
            problems.append(level)
            continue
        named.append(child.id)

    if shape.id is not None and await _closes_cycle(db, shape, named):
        problems.append("the change would make the entity a descendant of itself")
    return problems


async def _closes_cycle(db: Any, shape: EntityShape, named: list[UUID]) -> bool:
    """Whether, with the edit applied, ``shape`` reaches itself.

    The edit replaces the entity's own edges: its named children and its
    ``parent_id``. Walking down from its children, reaching the entity — or its
    new parent, which then reaches it through ``parent_id`` — is a cycle.
    """
    assert shape.id is not None
    stack: list[UUID] = list(named)
    stack += [c.id for c in await _row_children(db, shape.id, shape.company_id)]
    seen: set[UUID] = set()
    while stack:
        node = stack.pop()
        if node == shape.id or (shape.parent_id is not None and node == shape.parent_id):
            return True
        if node in seen:
            continue
        seen.add(node)
        entity = await _load(db, node, shape.company_id)
        if entity is None:
            continue
        stack += [r.entity_id for r in child_references(entity.hierarchy, entity.planning)
                  if r.entity_id is not None]
        stack += [c.id for c in await _row_children(db, node, shape.company_id) if c.id != shape.id]
    return False


async def _resolved_children(db: Any, entity: Any) -> tuple[list[tuple[str, Any]], list[str]]:
    """Every child of a stored entity, resolved the way the runtime resolves it."""
    from src.ai.planning.child_resolver import EntityNotFoundError, resolve_child_entity_id

    company_id = _as_uuid(getattr(entity, "company_id", None))
    found: list[tuple[str, Any]] = []
    problems: list[str] = []
    for ref in child_references(entity.hierarchy, entity.planning):
        child_id = ref.entity_id
        if child_id is None and ref.step is not None:
            try:
                child_id = await resolve_child_entity_id(ref.step, entity, db)
            except EntityNotFoundError:
                what = f"'{ref.raw}'" if ref.raw else "no entity"
                problems.append(f"{entity.name}: {ref.where} names {what}, which resolves to no entity in this company")
                continue
        if child_id is None:
            problems.append(f"{entity.name}: {ref.where} is not an entity id ({ref.raw!r})")
            continue
        child = await _load(db, child_id, company_id)
        if child is None:
            problems.append(f"{entity.name}: {ref.where} names {child_id}, which does not exist in this company")
            continue
        found.append((ref.where, child))
    for child in await _row_children(db, entity.id, company_id):
        found.append(("a child row (parent_id)", child))
    return found, problems


async def dispatch_violations(db: Any, root: Any) -> list[str]:
    """What stops ``root``'s whole tree from running.

    Walks every descendant once (depth-first), resolving invocation steps the
    way ``create_child_run`` will, and reports each edge that breaks the rule.
    """
    problems: list[str] = []
    on_path: set[UUID] = set()
    done: set[UUID] = set()

    async def walk(entity: Any) -> None:
        on_path.add(entity.id)
        children, unresolved = await _resolved_children(db, entity)
        problems.extend(unresolved)
        parent_type = _type_name(entity.type)
        for where, child in children:
            if child.id in on_path:
                problems.append(f"{entity.name}: {where} names {child.name}, which is its own ancestor (a cycle)")
                continue
            level = (_level_problem(f"{entity.name}: {where}", parent_type, child)
                     or _status_problem(f"{entity.name}: {where}", entity, child))
            if level:
                problems.append(level)
                continue
            if child.id not in done:
                await walk(child)
        on_path.discard(entity.id)
        done.add(entity.id)

    await walk(root)
    # One message per problem, in the order found.
    return list(dict.fromkeys(problems))


def runtime_violation(parent: Any, child: Any) -> Optional[str]:
    """Why ``child`` may not run as a child of ``parent``, or ``None``.

    The in-memory half of the rule, for a child the runtime resolved: same
    company, the level rule and the status rule. (Existence and deletion are
    the caller's company-scoped load.)
    """
    if _as_uuid(getattr(child, "company_id", None)) != _as_uuid(getattr(parent, "company_id", None)):
        return f"{child.name} does not belong to {parent.name}'s company"
    return (_level_problem("the step", _type_name(parent.type), child)
            or _status_problem("the step", parent, child))


# ── Depth (EP-06, EP-28) ────────────────────────────────────────────────────

def max_recursion_depth(governance: Any) -> int:
    """How deep the tree below an entity may go.

    ``governance.max_recursion_depth``; a stored ``execution_limits`` copy (the
    builder's old spelling) wins when present, as the schema's fold does.
    """
    gov = governance if isinstance(governance, dict) else {}
    limits = gov.get("execution_limits")
    candidates = [limits.get("max_recursion_depth") if isinstance(limits, dict) else None,
                  gov.get("max_recursion_depth")]
    for raw in candidates:
        if raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            return value
    return DEFAULT_MAX_RECURSION_DEPTH


@dataclass(frozen=True)
class ChildDepth:
    depth: int                 # the child run's depth
    max_depth: int             # the deepest a descendant of the child may go
    refused: Optional[str]     # why the child may not start, or None


def child_depth(parent_run: Any, parent_entity: Any, child_entity: Any) -> ChildDepth:
    """The depth of a child run of ``parent_run``, and whether it may start.

    A run's ``max_depth`` is the tightest limit on the way down: the root's
    ``depth + max_recursion_depth``, narrowed by every descendant's own limit.
    A top-level run's is derived from its entity when it first dispatches.
    """
    parent_depth = int(getattr(parent_run, "depth", 0) or 0)
    parent_max = getattr(parent_run, "max_depth", None)
    if parent_max is None:
        parent_max = parent_depth + max_recursion_depth(getattr(parent_entity, "governance", None))
    depth = parent_depth + 1
    own_max = depth + max_recursion_depth(getattr(child_entity, "governance", None))
    refused = None
    if depth > parent_max:
        refused = (
            f"{getattr(child_entity, 'name', 'the child')} would run at depth {depth}, "
            f"past this tree's max_recursion_depth (deepest allowed: {parent_max})"
        )
    return ChildDepth(depth=depth, max_depth=min(parent_max, own_max), refused=refused)


# ── Fan-out (AK-07) ─────────────────────────────────────────────────────────

def max_concurrent_children(governance: Any) -> int:
    """How many child runs one parent may have in flight at once.

    ``governance.max_concurrent_children``; a missing, non-numeric or
    non-positive value means the default.
    """
    raw = governance.get("max_concurrent_children") if isinstance(governance, dict) else None
    if raw is None:
        return DEFAULT_MAX_CONCURRENT_CHILDREN
    try:
        cap = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_CONCURRENT_CHILDREN
    return cap if cap >= 1 else DEFAULT_MAX_CONCURRENT_CHILDREN


# ── Entity status (EP-09) ───────────────────────────────────────────────────

# Which status an update may move an entity to. DELETED is reached only through
# DELETE (it cascades to the tree and keeps the row for billing).
ENTITY_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"ACTIVE", "ARCHIVED"}),
    "ACTIVE": frozenset({"DRAFT", "DEPRECATED", "ARCHIVED"}),
    "DEPRECATED": frozenset({"ACTIVE", "ARCHIVED"}),
    "ARCHIVED": frozenset({"DRAFT", "ACTIVE"}),
    "DELETED": frozenset(),
}


def status_transition_problem(current: Any, target: Any) -> Optional[str]:
    """Why an update may not move an entity from ``current`` to ``target``, or None."""
    now, to = _type_name(current), _type_name(target)
    if now == to:
        return None
    if to == "DELETED":
        return "an entity is deleted with DELETE, not by setting its status"
    if to not in ENTITY_STATUS_TRANSITIONS.get(now, frozenset()):
        return f"an entity cannot go from {now} to {to}"
    return None
