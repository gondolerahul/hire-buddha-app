"""Phase 14 WS3 (tech spec §7.5): the trigger filter language.

Safe JSON evaluated in Python — no code runs. A missing value makes a
comparison false rather than an error; depth and size are limited.
"""
import pytest

from src.automation.filters import MAX_CONDITIONS, FilterError, matches, validate

COMMENT = {
    "type": "social.comment.created",
    "source": "connector:instagram/17841400000000",
    "data": {"platform": "instagram", "text": "Do you SHIP to Pune? What's the price?",
             "author": {"name": "Priya", "followers": 1200}, "tags": ["lead", "Pune"]},
}

SPEC_EXAMPLE = {"all": [
    {"path": "data.platform", "op": "eq", "value": "instagram"},
    {"any": [
        {"path": "data.text", "op": "contains", "value": "price"},
        {"path": "data.text", "op": "contains", "value": "ship"}]}]}


def test_the_spec_example():
    assert matches(validate(SPEC_EXAMPLE), COMMENT)
    other = {**COMMENT, "data": {**COMMENT["data"], "text": "Lovely photo"}}
    assert not matches(SPEC_EXAMPLE, other)


@pytest.mark.parametrize("condition, expected", [
    ({"path": "data.author.followers", "op": "gt", "value": 1000}, True),
    ({"path": "data.author.followers", "op": "lte", "value": 1000}, False),
    ({"path": "data.author.followers", "op": "eq", "value": 1200.0}, True),   # 1200 is 1200.0
    ({"path": "data.author.followers", "op": "eq", "value": "1200"}, False),  # text is not a number
    ({"path": "data.author.name", "op": "in", "value": ["Priya", "Ravi"]}, True),
    ({"path": "data.author.name", "op": "nin", "value": ["Priya"]}, False),
    ({"path": "data.text", "op": "starts_with", "value": "do you"}, True),     # ignoring case
    ({"path": "data.tags", "op": "contains", "value": "pune"}, True),          # list membership
    ({"path": "data.author.email", "op": "exists"}, False),
    ({"path": "data.author.email", "op": "exists", "value": False}, True),
    ({"path": "data.author.email", "op": "eq", "value": "x"}, False),           # missing: false, no error
    ({"path": "data.author.email", "op": "ne", "value": "x"}, True),
    ({"path": "data.author.followers", "op": "gt", "value": "1000"}, False),    # number vs text: no match
    ({"path": "data.tags.0", "op": "eq", "value": "lead"}, True),
])
def test_operators(condition, expected):
    assert matches(validate(condition), COMMENT) is expected


def test_changed_reads_a_data_events_changed_fields():
    paid = {"type": "record.order.updated", "data": {"id": "o1", "changed": ["status", "paid_at"],
                                                     "after": {"status": "paid"}}}
    spec = {"all": [{"op": "changed", "value": "status"},
                    {"path": "data.after.status", "op": "eq", "value": "paid"}]}
    assert matches(validate(spec), paid)
    assert not matches(spec, {**paid, "data": {**paid["data"], "changed": ["notes"]}})


def test_booleans_are_not_numbers():
    event = {"data": {"vip": True, "count": 1}}
    assert matches({"path": "data.vip", "op": "eq", "value": True}, event)
    assert not matches({"path": "data.count", "op": "eq", "value": True}, event)


def test_an_empty_filter_matches_everything():
    assert matches(validate(None), COMMENT) and matches(validate({}), COMMENT)


@pytest.mark.parametrize("spec, message", [
    ({"path": "data.x", "op": "regex", "value": ".*"}, "op must be one of"),
    ({"path": "data.x", "op": "eq"}, "needs a value"),
    ({"path": "", "op": "eq", "value": 1}, "path must be"),
    ({"path": "data..x", "op": "eq", "value": 1}, "path must be"),
    ({"path": "data.x", "op": "in", "value": "a"}, "non-empty list"),
    ({"all": []}, "non-empty list"),
    ({"all": [{"path": "a.b", "op": "eq", "value": 1}], "any": []}, "exactly one key"),
    ({"path": "a.b", "op": "eq", "value": 1, "code": "import os"}, "unknown key"),
    ({"op": "changed"}, "field name"),
    ("data.text contains price", "must be an object"),
])
def test_invalid_filters_say_why(spec, message):
    with pytest.raises(FilterError, match=message):
        validate(spec)


def test_depth_and_size_are_limited():
    deep = {"path": "a.b", "op": "eq", "value": 1}
    for _ in range(4):
        deep = {"all": [deep]}
    with pytest.raises(FilterError, match="deeper than"):
        validate(deep)
    many = {"any": [{"path": "data.n", "op": "eq", "value": i} for i in range(MAX_CONDITIONS + 1)]}
    with pytest.raises(FilterError, match="more than"):
        validate(many)
