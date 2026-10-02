"""ai.core.run_blocks — the prompt blocks a run computes once, at compose.

Each lands in the run's context under an internal key that the step prompt's
layer 9 shows beside memory (``step_executor.prompt_context_block``):

* ``__subjects__`` — the people, records and files the run may act on, as the
  refs its tools take (TL-09);
* ``__failure_patterns__`` — what went wrong in the entity's recent failed
  runs and how to avoid it (PC-12).

A block that cannot be built is left out; the run goes on without it.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["add_run_blocks"]


async def add_run_blocks(db: Any, state: Any, run_id: Any) -> None:
    """Put the run's subjects and failure patterns into its context."""
    try:
        from src.ai.governance.subjects import subject_scope
        block = (await subject_scope(db, run_id, state.company_id)).render()
        if block:
            state.context_state["__subjects__"] = block
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not list the run's subjects: %s", exc)
    try:
        from src.ai.failure_pattern_service import FailurePatternService, render_failure_patterns
        block = render_failure_patterns(await FailurePatternService(db).get_failure_patterns(state.entity_id))
        if block:
            state.context_state["__failure_patterns__"] = block
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read the entity's failure patterns: %s", exc)
