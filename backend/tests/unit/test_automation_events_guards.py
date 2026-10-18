"""Phase 14 WS3 (tech spec §7.2, §7.8, §7.10): event ids and types, and the
safety rails' decisions. Every limit is the business's (decision D47): with
none set nothing is stopped; with one set, loops stop, overlaps follow the
rule, and agents stay inside it. Paused automation always holds.
"""
from datetime import datetime

import pytest

from datetime import timedelta

from src.automation import guards
from src.automation.limits import NO_LIMITS, AutomationLimits
from src.automation.events import (
    Envelope,
    EventError,
    schedule_dedupe_key,
    type_matches,
    uuid7,
    uuid7_time,
    validate_custom_type,
)


def test_uuid7_is_time_ordered_and_versioned():
    ids = [uuid7(1_760_000_000_000 + i) for i in range(50)]
    assert ids == sorted(ids) and len(set(ids)) == 50
    assert all(i.version == 7 and i.variant == "specified in RFC 4122" for i in ids)
    assert uuid7_time(ids[0]) == datetime(2025, 10, 9, 8, 53, 20)


def test_custom_events_only_for_agents():
    assert validate_custom_type("custom.lead_qualified") == "custom.lead_qualified"
    for forbidden in ("record.order.updated", "social.comment.created", "schedule.fired",
                      "custom.", "custom.Lead", "lead_qualified", "custom.a b"):
        with pytest.raises(EventError):
            validate_custom_type(forbidden)


@pytest.mark.parametrize("pattern, event_type, expected", [
    ("social.comment.created", "social.comment.created", True),
    ("record.order.*", "record.order.updated", True),
    ("record.order.*", "record.orders.updated", False),
    ("record.*", "record.shipment.created", True),
    ("social.comment.created", "social.comment.deleted", False),
])
def test_trigger_type_patterns(pattern, event_type, expected):
    assert type_matches(pattern, event_type) is expected


def test_one_schedule_event_per_trigger_per_time():
    at = datetime(2026, 10, 19, 3, 30, 0, 123456)
    assert schedule_dedupe_key("t1", at) == schedule_dedupe_key("t1", at.replace(microsecond=0))
    assert schedule_dedupe_key("t1", at) != schedule_dedupe_key("t2", at)


def test_an_event_caused_by_a_run_is_one_step_deeper():
    root = Envelope(type="social.comment.created", source="connector:instagram/1", dedupe_key="ig:c1")
    assert root.correlation_id == root.id and root.chain_depth == 0
    child = root.caused("custom.lead_qualified", data={"lead": "x"}, source="run:r1", dedupe_key="run:r1:1")
    grandchild = child.caused("custom.follow_up", data={}, source="run:r2", dedupe_key="run:r2:1")
    assert (child.chain_depth, grandchild.chain_depth) == (1, 2)
    assert child.causation_id == root.id and grandchild.correlation_id == root.id
    assert child.trust == "internal"
    assert root.as_dict()["time"].endswith("Z") and root.as_dict()["id"] == str(root.id)


@pytest.mark.parametrize("kwargs, message", [
    ({"type": "Not A Type"}, "event type"),
    ({"trust": "maybe"}, "trust"),
    ({"dedupe_key": ""}, "dedupe_key"),
    ({"chain_depth": -1}, "negative"),
])
def test_bad_envelopes(kwargs, message):
    base = {"type": "custom.x", "source": "s", "dedupe_key": "k"}
    with pytest.raises(EventError, match=message):
        Envelope(**{**base, **kwargs})


def test_without_limits_nothing_is_stopped():
    assert guards.chain_depth(10_000, NO_LIMITS) is None
    assert guards.rate(10_000, None, NO_LIMITS) is None
    assert guards.overlap(50, None, None, NO_LIMITS).outcome == guards.STARTED   # default: allow
    assert guards.business_concurrency(10_000, NO_LIMITS) is None
    assert guards.catch_up_policy(None, NO_LIMITS) == "all"
    guards.agent_schedule(10_000, 10_000, NO_LIMITS)
    guards.agent_emit(10_000, NO_LIMITS)
    guards.wait_timeout(timedelta(days=3650), NO_LIMITS)
    assert guards.agent_min_repeat(NO_LIMITS) is None


def test_a_loop_stops_past_the_business_limit():
    limits = AutomationLimits(max_chain_depth=5)
    assert guards.chain_depth(5, limits) is None
    stopped = guards.chain_depth(6, limits)
    assert stopped.outcome == guards.SKIPPED_CHAIN_DEPTH and "loop stopped" in stopped.reason


def test_a_triggers_own_rate_wins():
    limits = AutomationLimits(trigger_rate_per_hour=60)
    assert guards.rate(59, None, limits) is None
    assert guards.rate(60, None, limits).outcome == guards.SKIPPED_RATE
    assert guards.rate(60, 100, limits) is None


@pytest.mark.parametrize("policy, active, expected", [
    ("skip", 0, guards.STARTED), ("skip", 1, guards.SKIPPED_OVERLAP),
    ("queue", 1, guards.QUEUED), ("allow", 3, guards.STARTED),
])
def test_overlap_rules(policy, active, expected):
    assert guards.overlap(active, policy, None, NO_LIMITS).outcome == expected


def test_the_business_overlap_rule_applies_when_the_trigger_has_none():
    limits = AutomationLimits(overlap="skip")
    assert guards.overlap(1, None, None, limits).outcome == guards.SKIPPED_OVERLAP
    assert guards.overlap(1, "allow", None, limits).outcome == guards.STARTED


def test_concurrency_allows_several_runs_of_one_trigger():
    assert guards.overlap(2, "skip", 3, NO_LIMITS).outcome == guards.STARTED
    assert guards.overlap(3, "skip", 3, NO_LIMITS).outcome == guards.SKIPPED_OVERLAP


def test_paused_automation_holds_and_busy_businesses_queue():
    assert guards.automation_state("running") is None
    assert guards.automation_state("paused").outcome == guards.BLOCKED_PAUSED
    limits = AutomationLimits(max_active_runs=20)
    assert guards.business_concurrency(19, limits) is None
    assert guards.business_concurrency(20, limits).outcome == guards.QUEUED


def test_agent_limits_when_set():
    limits = AutomationLimits(agent_max_schedules=50, agent_schedules_per_run=5, agent_events_per_run=20,
                              max_wait_days=30, agent_min_repeat_minutes=15)
    guards.agent_schedule(49, 4, limits)
    with pytest.raises(guards.AgentLimitExceeded, match="cancel one"):
        guards.agent_schedule(50, 0, limits)
    with pytest.raises(guards.AgentLimitExceeded, match="at most 5"):
        guards.agent_schedule(0, 5, limits)
    guards.agent_emit(19, limits)
    with pytest.raises(guards.AgentLimitExceeded, match="at most 20"):
        guards.agent_emit(20, limits)
    with pytest.raises(guards.AgentLimitExceeded, match="30 days"):
        guards.wait_timeout(timedelta(days=31), limits)
    assert guards.agent_min_repeat(limits) == timedelta(minutes=15)
