"""The safety rails' decisions (tech spec §7.8, §7.10; functional spec §3.3, §3.5).

Pure functions: given what the router or a tool knows and the limits in
force (``limits.AutomationLimits``), the outcome a trigger firing or an agent
call gets and the reason recorded with it. A limit that is ``None`` is not
checked: every limit is the business's choice, none by default (D47). The
router applies them in this order: paused automation, chain depth, rate,
overlap, business concurrency, budget, policy. The wallet check (D06) is not
a limit and always applies.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from src.automation.limits import AutomationLimits

OVERLAP_POLICIES = ("skip", "queue", "allow")

# Firing outcomes recorded in platform.trigger_firings (§7.3).
STARTED = "started"
QUEUED = "queued"
SKIPPED_OVERLAP = "skipped_overlap"
SKIPPED_RATE = "skipped_rate"
SKIPPED_CHAIN_DEPTH = "skipped_chain_depth"
SKIPPED_CONDITION_FALSE = "skipped_condition_false"
SKIPPED_MISSED = "skipped_missed"  # a schedule time missed while down or paused; catch-up said skip
BLOCKED_BUDGET = "blocked_budget"
BLOCKED_PAUSED = "blocked_paused"
BLOCKED_POLICY = "blocked_policy"
FAILED = "failed"


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str = ""

    @property
    def starts(self) -> bool:
        return self.outcome in (STARTED, QUEUED)


def automation_state(state: str) -> Optional[Decision]:
    """Paused automation holds new events; they run in order when it resumes."""
    if state != "running":
        return Decision(BLOCKED_PAUSED, f"held: automation is {state}")
    return None


def chain_depth(depth: int, limits: AutomationLimits) -> Optional[Decision]:
    """A chain of agent-caused events stops past the business's loop limit, if it set one."""
    maximum = limits.max_chain_depth
    if maximum is not None and depth > maximum:
        return Decision(SKIPPED_CHAIN_DEPTH, f"loop stopped: chain depth {depth} is over the limit of {maximum}")
    return None


def rate(started_last_hour: int, trigger_rate: Optional[int], limits: AutomationLimits) -> Optional[Decision]:
    """Runs one trigger may start an hour: its own rate, else the business's, else none."""
    maximum = trigger_rate if trigger_rate is not None else limits.trigger_rate_per_hour
    if maximum is not None and started_last_hour >= maximum:
        return Decision(SKIPPED_RATE, f"skipped: {started_last_hour} runs in the last hour (limit {maximum})")
    return None


def overlap(active_runs: int, trigger_policy: Optional[str], max_concurrency: Optional[int],
            limits: AutomationLimits) -> Decision:
    """The trigger's rule when earlier runs are still going (its own, else the business's)."""
    policy = trigger_policy or limits.overlap
    if policy not in OVERLAP_POLICIES:
        raise ValueError(f"overlap must be one of {', '.join(OVERLAP_POLICIES)}")
    allowed = max(1, max_concurrency or 1)
    if policy == "allow" or active_runs < allowed:
        return Decision(STARTED)
    if policy == "queue":
        return Decision(QUEUED, f"queued: {active_runs} run(s) of this trigger still going")
    return Decision(SKIPPED_OVERLAP, f"skipped: {active_runs} run(s) of this trigger still going")


def business_concurrency(active_runs: int, limits: AutomationLimits) -> Optional[Decision]:
    """Automated runs the business may have going at once, if it set a limit."""
    maximum = limits.max_active_runs
    if maximum is not None and active_runs >= maximum:
        return Decision(QUEUED, f"queued: {active_runs} automated runs going (limit {maximum})")
    return None


def catch_up_policy(trigger_policy: Optional[str], limits: AutomationLimits) -> str:
    return trigger_policy or limits.catch_up


class AgentLimitExceeded(ValueError):
    """An agent tool call over a limit; the message is what the agent is told."""


def agent_schedule(active_agent_triggers: int, created_this_run: int, limits: AutomationLimits) -> None:
    """``schedule_agent``: the business's limits on agent-made schedules, if any."""
    if limits.agent_max_schedules is not None and active_agent_triggers >= limits.agent_max_schedules:
        raise AgentLimitExceeded(f"the business already has {active_agent_triggers} schedules made by agents "
                                 f"(limit {limits.agent_max_schedules}); cancel one first")
    if limits.agent_schedules_per_run is not None and created_this_run >= limits.agent_schedules_per_run:
        raise AgentLimitExceeded(f"a run may create at most {limits.agent_schedules_per_run} schedules")


def agent_min_repeat(limits: AutomationLimits) -> Optional[timedelta]:
    """The shortest repeat an agent's schedule may have, or ``None``."""
    minutes = limits.agent_min_repeat_minutes
    return timedelta(minutes=minutes) if minutes is not None else None


def agent_emit(emitted_this_run: int, limits: AutomationLimits) -> None:
    """``emit_event``: the business's limit on signals per run, if any."""
    if limits.agent_events_per_run is not None and emitted_this_run >= limits.agent_events_per_run:
        raise AgentLimitExceeded(f"a run may emit at most {limits.agent_events_per_run} events")


def wait_timeout(requested: timedelta, limits: AutomationLimits) -> None:
    """``wait_for_event``: the business's longest wait, if any."""
    if limits.max_wait_days is not None and requested > timedelta(days=limits.max_wait_days):
        raise AgentLimitExceeded(f"a run may wait at most {limits.max_wait_days} days")
