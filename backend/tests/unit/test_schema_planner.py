"""The blueprint, base pack v1 and the change planner (WS4 4.1–4.3; tech spec
§8): names and types are checked, the base pack becomes its tables, a
business's additions stay in ``custom`` / ``x_``, risky changes are checked
first or refused, renames keep the old name for two versions."""
from __future__ import annotations

import pytest

from src.schema_engine import base_pack
from src.schema_engine import blueprint as bp
from src.schema_engine.planner import PlanError, plan


@pytest.fixture
def with_base():
    return plan(bp.empty(), base_pack.operations(), actor="platform").blueprint


def test_names_and_types_are_checked():
    for bad in ("Contact", "1st", "filter", "id", "a", "x" * 49):
        with pytest.raises(bp.BlueprintError):
            bp.check_name(bad, "field")
    with pytest.raises(bp.BlueprintError, match="no JSON"):
        bp.validate_field("data", {"type": "json"}, where="f", known_objects=[])
    with pytest.raises(bp.BlueprintError, match="to must name"):
        bp.validate_field("order", {"type": "ref", "to": "nowhere"}, where="f", known_objects=["contact"])
    with pytest.raises(bp.BlueprintError, match="default"):
        bp.validate_field("stage", {"type": "enum", "values": ["a"], "default": "b"}, where="f", known_objects=[])


def test_the_base_pack_is_its_tables_and_its_blueprint(with_base):
    result = plan(bp.empty(), base_pack.operations(), actor="platform")
    sql = [s.sql for s in result.statements]
    assert sql[0].startswith('CREATE TABLE "business"."account" ("id" uuid PRIMARY KEY DEFAULT gen_random_uuid()')
    contact = next(s for s in sql if s.startswith('CREATE TABLE "business"."contact"'))
    assert '"lifecycle_stage" text DEFAULT \'lead\'' in contact
    assert 'FOREIGN KEY ("account") REFERENCES "business"."account" ("id") ON DELETE SET NULL' in contact
    assert "CHECK (\"lifecycle_stage\" IN ('subscriber', 'lead'" in contact
    assert set(with_base["objects"]) == {"account", "contact", "activity", "consent"}
    assert all(o["platform"] and o["storage"]["schema"] == "business" for o in with_base["objects"].values())
    assert with_base["version"] == 1 and result.additive


def test_a_business_adds_its_own_objects_in_custom_and_x_fields_on_platform_objects(with_base):
    result = plan(with_base, [
        {"op": "add_object", "object": "shipment", "definition": {"fields": {
            "contact": {"type": "ref", "to": "contact", "on_delete": "restrict", "required": True},
            "status": {"type": "enum", "values": ["pending", "delivered"], "default": "pending"},
            "weight": {"type": "decimal", "precision": 10, "scale": 2},
            "price": {"type": "money"}}, "indexes": [["status"]]}},
        {"op": "add_field", "object": "contact", "field": "x_loyalty_tier", "definition": {"type": "text"}},
    ])
    sql = " ".join(s.sql for s in result.statements)
    assert 'CREATE TABLE "custom"."shipment"' in sql and '"price_currency" char(3)' in sql
    assert 'ALTER TABLE "business"."contact" ADD COLUMN "x_loyalty_tier" varchar(255)' in sql
    assert result.blueprint["version"] == 2 and result.additive

    with pytest.raises(PlanError, match="starts with x_"):
        plan(with_base, [{"op": "add_field", "object": "contact", "field": "tier", "definition": {"type": "text"}}])
    with pytest.raises(PlanError, match="schema custom"):
        plan(with_base, [{"op": "add_object", "object": "thing",
                          "definition": {"storage": {"schema": "business", "table": "thing"}, "fields": {}}}])
    with pytest.raises(PlanError, match="only by the platform"):
        plan(with_base, [{"op": "archive_field", "object": "contact", "field": "email"}])


def test_risky_changes_are_checked_first_or_refused(with_base):
    required = plan(with_base, [{"op": "make_required", "object": "contact", "field": "source"}], actor="platform")
    assert required.checks and "IS NULL" in required.checks[0].sql and not required.additive
    unique = plan(with_base, [{"op": "add_unique", "object": "contact", "columns": ["external_ref"]}], actor="platform")
    assert "HAVING count(*) > 1" in unique.checks[0].sql
    with pytest.raises(PlanError, match="cannot be changed in place"):
        plan(with_base, [{"op": "change_type", "object": "contact", "field": "source"}])
    with pytest.raises(PlanError, match="needs a default"):
        plan(with_base, [{"op": "add_field", "object": "contact", "field": "x_code",
                          "definition": {"type": "text", "required": True}}], row_counts={"contact": 5})


def test_a_big_table_gets_its_index_concurrently(with_base):
    result = plan(with_base, [{"op": "add_index", "object": "contact", "columns": ["source"]}],
                  row_counts={"contact": 250_000})
    assert result.statements[0].concurrently and "CONCURRENTLY" in result.statements[0].sql


def test_a_renamed_field_answers_to_its_old_name_for_two_versions(with_base):
    v2 = plan(with_base, [{"op": "add_object", "object": "visit", "definition": {"fields": {
        "when": {"type": "datetime"}}}}]).blueprint
    v3 = plan(v2, [{"op": "rename_field", "object": "visit", "field": "when", "to": "visited_at"}])
    assert 'RENAME COLUMN "when" TO "visited_at"' in v3.statements[0].sql
    visit = v3.blueprint["objects"]["visit"]
    assert bp.resolve_field(visit, "when") == "visited_at"
    v4 = plan(v3.blueprint, [{"op": "add_index", "object": "visit", "columns": ["visited_at"]}]).blueprint
    v5 = plan(v4, [{"op": "add_index", "object": "visit", "columns": ["created_at"]}]).blueprint
    assert bp.resolve_field(v5["objects"]["visit"], "when") == "visited_at"  # v5 = 3 + 2: still answers
    v6 = plan(v5, [{"op": "add_index", "object": "visit", "columns": ["updated_at"]}]).blueprint
    with pytest.raises(bp.BlueprintError):
        bp.resolve_field(v6["objects"]["visit"], "when")


def test_an_object_still_referred_to_cannot_be_archived(with_base):
    v2 = plan(with_base, [{"op": "add_object", "object": "order", "definition": {"fields": {
        "number": {"type": "text"}}}},
        {"op": "add_object", "object": "shipment", "definition": {"fields": {
            "order": {"type": "ref", "to": "order"}}}}]).blueprint
    with pytest.raises(PlanError, match="refers to order"):
        plan(v2, [{"op": "archive_object", "object": "order"}])
    archived = plan(v2, [{"op": "archive_field", "object": "shipment", "field": "order"},
                         {"op": "archive_object", "object": "order"}]).blueprint
    assert "order" not in bp.objects(archived) and archived["objects"]["order"]["archived"]
