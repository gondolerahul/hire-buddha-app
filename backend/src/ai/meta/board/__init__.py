"""
ai.meta.board — what is left of the Meta-Agent Architecture Board (MI-20, D27).

The seven-role Board (RequirementChat, Curator, Architect, Critic, Validator,
TestDriver, Promoter) was built with tests and never constructed by any
creation path. Two roles do real work and stay:

    ValidatorRole — deterministic checks every publication passes
                    (``src/ai/governance/publication.py``)
    ToolSmith     — drafts a tool's source for the tool-synthesis pipeline

The rest was deleted on 2026-10-03; git keeps it.
"""
from src.ai.meta.board.validator import ValidatorReport, ValidatorRole

__all__ = ["ValidatorRole", "ValidatorReport"]
