"""
tests.harness.infra — what a tier does when its Postgres or Redis is missing.

Locally, a missing database skips the integration and parity tiers, so a
developer without Docker still gets a unit run. With ``REQUIRE_DB=1`` (set it on
any gating run) the same condition fails the run instead (TS-05): a green run with every
infrastructure test skipped proves nothing.
"""
from __future__ import annotations

import os
from typing import NoReturn

import pytest

_TRUTHY = {"1", "true", "yes", "on"}


def infra_required() -> bool:
    """Whether ``REQUIRE_DB`` asks for missing infrastructure to fail the run."""
    return os.environ.get("REQUIRE_DB", "").strip().lower() in _TRUTHY


def infra_unavailable(reason: str) -> NoReturn:
    """Skip with ``reason`` — or, under ``REQUIRE_DB=1``, fail with it."""
    if infra_required():
        pytest.fail(f"{reason} (REQUIRE_DB=1: missing infrastructure fails the run)", pytrace=False)
    pytest.skip(reason)
