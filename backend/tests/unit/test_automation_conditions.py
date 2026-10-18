"""Condition triggers' checks (WS4 4.10): what a condition may say, and how it compares."""
import pytest

from src.automation import conditions, triggers
from src.automation.conditions import ConditionError, _compare, describe, validate


def test_a_condition_is_stored_in_one_form():
    assert validate({"object": "product", "filter": [{"field": "stock", "op": "lt", "value": 10}]}) == {
        "object": "product", "filter": [["stock", "lt", 10]], "measure": {"fn": "count"}, "op": "gt", "value": 0}
    assert validate({"object": "order", "filter": [["status", "eq", "paid"]],
                     "measure": {"fn": "sum", "field": "total"}, "op": "gte", "value": "1000.50"})["measure"] == \
        {"fn": "sum", "field": "total"}


@pytest.mark.parametrize("spec, says", [
    (None, "needs a condition"),
    ({}, "condition.object"),
    ({"object": "p", "filter": [{"op": "eq"}]}, "{field, op, value}"),
    ({"object": "p", "filter": [{"field": "x", "op": "like"}]}, "op is one of"),
    ({"object": "p", "measure": {"fn": "median"}}, "measure.fn"),
    ({"object": "p", "measure": {"fn": "sum"}}, "sum needs a field"),
    ({"object": "p", "op": "between"}, "condition.op"),
    ({"object": "p", "value": True}, "a number"),
    ({"object": "p", "value": "ten"}, "a number"),
    ({"object": "p", "filter": [["x", "eq", 1]] * 21}, "at most 20"),
])
def test_a_condition_that_cannot_be_checked_is_refused(spec, says):
    with pytest.raises(ConditionError, match=says.replace("{", r"\{").replace("}", r"\}")):
        validate(spec)


def test_comparisons_and_empty_results():
    assert _compare(3, "gt", 0) and not _compare(0, "gt", 0)
    assert _compare("12.50", "gte", 12.5) and _compare(9, "lt", "10") and _compare(4, "ne", 5)
    assert not _compare(None, "lt", 10)          # an average of no records holds nothing


def test_the_owner_reads_what_was_checked():
    spec = validate({"object": "product", "filter": [["stock", "lt", 10]], "op": "gt", "value": 0})
    assert describe(spec, 3) == "count of product where stock lt 10 is 3 (> 0)"


def test_a_condition_trigger_is_a_schedule_with_a_check():
    from datetime import datetime
    import uuid

    base = {"kind": "condition", "name": "Low stock", "entity_id": uuid.uuid4(), "cron": "0 * * * *"}
    with pytest.raises(triggers.TriggerError, match="needs a condition"):
        triggers.validate(base, now=datetime.utcnow())
    saved = triggers.validate({**base, "condition": {"object": "product", "filter": [["stock", "lt", 10]]}},
                              now=datetime.utcnow())
    assert saved["condition"]["filter"] == [["stock", "lt", 10]]
    with pytest.raises(triggers.TriggerError, match="cron"):
        triggers.validate({**base, "cron": None, "condition": {"object": "product"}}, now=datetime.utcnow())
    assert triggers.validate({**base, "kind": "schedule", "condition": {"object": "x"}},
                             now=datetime.utcnow())["condition"] is None
    assert conditions.MEASURES[0] == "count"
