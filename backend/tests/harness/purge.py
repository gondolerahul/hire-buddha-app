"""
tests.harness.purge — delete the companies a test session created, and every
row that references them.

Used by the suites that commit to the shared dev database: e2e (its own
companies and users) and parity (its ``parity-*`` tenants, TS-16). The walk is
the product's own (``src.offboarding.purge``, the control half of deleting a
test business, docs/phase15/13 §10); this module keeps the import path the
suites use.
"""
from __future__ import annotations

from src.offboarding.purge import purge_companies

__all__ = ["purge_companies"]
