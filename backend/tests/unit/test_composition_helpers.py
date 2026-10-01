"""The in-memory half of the composition rule (``ai.governance.composition``)."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from src.ai.governance.composition import (
    EntityShape,
    child_references,
    runtime_violation,
)


def test_child_references_reads_the_hierarchy_and_the_static_plan() -> None:
    a, b = uuid4(), uuid4()
    refs = child_references(
        {"children": [{"child_id": str(a)}, {"child_type": "SKILL"}]},
        {"static_plan": {"steps": [
            {"name": "Write", "type": "child_entity_invocation", "target": {"entity_id": str(b)}},
            {"name": "Fetch", "type": "TOOL_CALL", "target": {"tool_id": "web_search"}},
            {"name": "Later", "type": "CHILD_ENTITY_INVOCATION", "target": {"entity_name_hint": "__PLACEHOLDER__"}},
        ]}},
    )
    assert [(r.where, r.entity_id, r.raw) for r in refs] == [
        ("hierarchy.children[0]", a, str(a)),
        ("step 'Write'", b, str(b)),
        ("step 'Later'", None, "__PLACEHOLDER__"),
    ]
    assert refs[2].step is not None and refs[0].step is None


def test_child_references_tolerates_missing_blocks() -> None:
    assert child_references(None, None) == []
    assert child_references({"children": None}, {"static_plan": None}) == []


def test_an_update_payload_reshapes_only_what_it_sends() -> None:
    parent = uuid4()
    shape = EntityShape(id=uuid4(), type="AGENT", company_id=uuid4(), parent_id=None,
                        hierarchy={"children": []}, planning=None, name="a")
    changed = shape.with_changes({"type": "process", "parent_id": str(parent)})
    assert changed.type == "PROCESS" and changed.parent_id == parent
    assert changed.hierarchy == {"children": []} and changed.name == "a"
    assert shape.with_changes({"parent_id": None}).parent_id is None


def _e(type_: str, company=None):
    return SimpleNamespace(id=uuid4(), type=type_, company_id=company or uuid4(), name=f"e-{type_.lower()}")


def test_runtime_refuses_a_child_above_the_parent_or_in_another_company() -> None:
    company = uuid4()
    assert runtime_violation(_e("PROCESS", company), _e("AGENT", company)) is None
    assert runtime_violation(_e("AGENT", company), _e("AGENT", company)) is None
    assert "PROCESS" in (runtime_violation(_e("AGENT", company), _e("PROCESS", company)) or "")
    assert "company" in (runtime_violation(_e("GRAPH", company), _e("ACTION")) or "")
