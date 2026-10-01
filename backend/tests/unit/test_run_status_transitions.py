"""A run's status follows the state machine; terminal statuses are final (DM-17).

``VALID_TRANSITIONS`` had no callers, so any status could follow any other — a
loop finishing after the user cancelled overwrote CANCELLED with COMPLETED —
and REPAIRING could never be entered. The run model now refuses a transition
the table does not list and keeps the old status.
"""
from __future__ import annotations

import logging

import pytest

from src.ai.orm.execution import ExecutionRun
from src.ai.schemas.enums import TERMINAL_RUN_STATUSES, VALID_TRANSITIONS, RunStatus, validate_transition


def _run(status: str) -> ExecutionRun:
    return ExecutionRun(status=status)


@pytest.mark.parametrize("terminal", sorted(TERMINAL_RUN_STATUSES))
@pytest.mark.parametrize("target", ["RUNNING", "COMPLETED", "FAILED", "PAUSED", "WAITING_ON_CHILDREN"])
def test_a_terminal_status_is_final(terminal, target, caplog):
    run = _run(terminal)
    with caplog.at_level(logging.WARNING):
        run.status = target
    assert run.status == terminal
    if target != terminal:
        assert "refused status change" in caplog.text


def test_a_late_completion_does_not_overwrite_a_cancel():
    run = _run("RUNNING")
    run.status = "CANCELLED"
    run.status = RunStatus.COMPLETED.value
    assert run.status == "CANCELLED"


@pytest.mark.parametrize("path", [
    ["PENDING", "RUNNING", "COMPLETED"],
    ["PENDING", "FAILED"],                      # refused before it started (credit gate)
    ["PENDING", "CANCELLED"],
    ["PENDING", "RUNNING", "WAITING_ON_CHILDREN", "WAITING_ON_CHILDREN", "RUNNING", "PARTIAL_COMPLETE"],
    ["PENDING", "RUNNING", "PAUSED", "RUNNING", "CANCELLED"],
    ["PENDING", "RUNNING", "RUNNING", "FAILED"],  # a re-delivered job sets RUNNING again
])
def test_the_pipelines_paths_are_allowed(path):
    run = _run(path[0])
    for status in path[1:]:
        run.status = status
        assert run.status == status


def test_the_table_is_closed_and_has_no_unreachable_status():
    statuses = {s.value for s in RunStatus}
    assert set(VALID_TRANSITIONS) == statuses
    assert all(targets <= statuses for targets in VALID_TRANSITIONS.values())
    assert "REPAIRING" not in statuses
    reachable = {"PENDING"} | set().union(*VALID_TRANSITIONS.values())
    assert reachable == statuses
    assert all(not VALID_TRANSITIONS[s] for s in TERMINAL_RUN_STATUSES)


def test_unknown_statuses_are_refused():
    assert validate_transition("RUNNING", "REPAIRING") is False
    assert validate_transition("REPAIRING", "RUNNING") is False
    assert validate_transition("RUNNING", "RUNNING") is True
