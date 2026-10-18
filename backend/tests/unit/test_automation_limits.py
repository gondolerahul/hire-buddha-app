"""Decision D47: every automation limit is the business's setting, none by default.

Absent inherits (business ← platform ← none); ``null`` means no limit even
when the platform has one; a value is the limit. Unknown names and bad
values are refused with a message naming the limit.
"""
import pytest

from src.automation.limits import (
    BY_KEY,
    CATALOGUE,
    NO_LIMITS,
    AutomationLimits,
    LimitsError,
    resolve,
    validate,
)


def test_nothing_set_means_no_limits():
    assert resolve(None, None) == NO_LIMITS
    assert NO_LIMITS.max_chain_depth is None and NO_LIMITS.overlap == "allow" and NO_LIMITS.catch_up == "all"


def test_the_catalogue_covers_every_limit_once():
    from dataclasses import fields

    assert [limit.key for limit in CATALOGUE] == [f.name for f in fields(AutomationLimits)]
    assert all(limit.label and limit.help for limit in CATALOGUE)
    assert BY_KEY["overlap"].choices == ("allow", "queue", "skip")


def test_business_values_win_over_the_platforms():
    platform = {"max_chain_depth": 5, "trigger_rate_per_hour": 60, "overlap": "skip"}
    business = {"max_chain_depth": 8, "trigger_rate_per_hour": None}
    limits = resolve(platform, business)
    assert limits.max_chain_depth == 8            # the business's value
    assert limits.trigger_rate_per_hour is None   # null: no limit, though the platform has one
    assert limits.overlap == "skip"               # absent: inherited from the platform


def test_a_null_choice_is_the_default_behaviour():
    assert resolve({"overlap": "skip"}, {"overlap": None}).overlap == "allow"


@pytest.mark.parametrize("values, message", [
    ({"loop_limit": 3}, "unknown limit"),
    ({"max_chain_depth": 0}, "max_chain_depth"),
    ({"max_chain_depth": -1}, "max_chain_depth"),
    ({"max_chain_depth": 2.5}, "max_chain_depth"),
    ({"max_chain_depth": True}, "max_chain_depth"),
    ({"max_chain_depth": "5"}, "max_chain_depth"),
    ({"overlap": "sometimes"}, "overlap"),
    ([1, 2], "an object"),
])
def test_bad_values_are_refused(values, message):
    with pytest.raises(LimitsError, match=message):
        validate(values)


def test_valid_values_pass():
    assert validate({"max_chain_depth": 5, "catch_up": "once", "event_retention_days": None}) == {
        "max_chain_depth": 5, "catch_up": "once", "event_retention_days": None}
    assert validate(None) == {}
