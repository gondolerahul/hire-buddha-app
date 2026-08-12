"""Import-shape assertions.

These tests freeze the cleanup work so it doesn't regress:

  * CortexService is importable from both its module and the package.
  * worker.py re-exports must be gone; the canonical paths under
    ``src.ai.core.*`` must work.
"""
from __future__ import annotations

import pytest


def test_cortex_service_canonical_import() -> None:
    """`from src.ai.memory.cortex_service import CortexService` works."""
    from src.ai.memory.cortex_service import CortexService

    assert CortexService.__name__ == "CortexService"


def test_memory_package_exposes_cortex_service() -> None:
    """`from src.ai.memory import CortexService` resolves."""
    from src.ai.memory import CortexService

    assert CortexService.__name__ == "CortexService"


def test_no_worker_re_exports() -> None:
    """`from src.ai.worker import ExecutionEngine` must raise — the
    Track 0 cleanup removed the worker re-exports."""
    with pytest.raises(ImportError):
        from src.ai.worker import ExecutionEngine  # noqa: F401


def test_canonical_step_engine_import() -> None:
    """The legacy ExecutionEngine.execute_run plan-walker was deleted (C4); the
    StepEngine step surface is the canonical engine the loop's executors use."""
    from src.ai.core.step_engine import StepEngine

    assert StepEngine.__name__ == "StepEngine"


def test_canonical_exception_import() -> None:
    from src.ai.core.exceptions import UncertaintySignal

    assert issubclass(UncertaintySignal, BaseException)
