"""Phase 11 Track 6 — ScopePolicy dataclass + ScopeViolation surface."""
from __future__ import annotations

import pytest

from src.ai.memory.scope_policy import ScopePolicy, ScopeViolation


def test_default_policy_is_strict() -> None:
    p = ScopePolicy()
    assert p.can_read_outside is False
    assert p.can_write_outside is False
    assert p.can_navigate_to_siblings is False
    assert p.error_on_violation is True


def test_child_recursion_default_allows_read_only() -> None:
    p = ScopePolicy.child_recursion_default()
    assert p.can_read_outside is True
    assert p.can_write_outside is False
    assert p.error_on_violation is True


def test_violation_carries_context() -> None:
    exc = ScopeViolation(
        operation="write",
        target_id="00000000-0000-0000-0000-000000000001",
        scope_root_id="00000000-0000-0000-0000-000000000002",
    )
    msg = str(exc)
    assert "write" in msg
    assert "00000000-0000-0000-0000-000000000001" in msg
    assert exc.operation == "write"
    assert exc.target_id == "00000000-0000-0000-0000-000000000001"
    assert exc.scope_root_id == "00000000-0000-0000-0000-000000000002"


def test_violation_is_raisable() -> None:
    with pytest.raises(ScopeViolation):
        raise ScopeViolation(operation="read", target_id="x", scope_root_id="r")
