"""
ai.meta.board — Phase 11 Track 5 Meta-Agent Architecture Board.

Each role is a small service class with one public coroutine. They are
called sequentially from the Meta-Agent's static plan (no separate
LLM agent per role; the deterministic ones — Validator, Promoter,
Curator-glue — run as pure code, while the Architect+Critic loops
share the existing LLM router).

Roles (in execution order)::

    1. RequirementChat  — clarify the user's request into a Spec
    2. Curator          — REUSE / ADAPT / COMPOSE / CREATE decision
    3. Architect        — produces the draft HierarchicalEntity payload
    4. Critic           — meta_spec_critic loop, up to 2 revise rounds
    5. Validator        — deterministic spec checks (cycle / tools / cost)
    6. TestDriver       — smoke + regression + boundary + hostile suite
    7. Promoter         — 6 gates → DRAFT → ACTIVE
"""
from src.ai.meta.board.architect import Architect, ArchitectDraft
from src.ai.meta.board.critic import BoardCritic, CriticReport
from src.ai.meta.board.curator import Curator, CuratorDecision
from src.ai.meta.board.promoter import (
    PromotionDecision,
    Promoter,
    PromoterGateResult,
)
from src.ai.meta.board.requirement_chat import RequirementChat, Spec
from src.ai.meta.board.test_driver import (
    SuiteResult,
    TestCaseResult,
    TestDriver,
)
from src.ai.meta.board.validator import ValidatorReport, ValidatorRole

__all__ = [
    "Architect", "ArchitectDraft",
    "BoardCritic", "CriticReport",
    "Curator", "CuratorDecision",
    "Promoter", "PromotionDecision", "PromoterGateResult",
    "RequirementChat", "Spec",
    "TestDriver", "TestCaseResult", "SuiteResult",
    "ValidatorRole", "ValidatorReport",
]
