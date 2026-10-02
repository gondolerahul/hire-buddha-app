"""One goal-validation setting; the shims with no live caller are gone (P7.8 —
PC-17, PC-10).

Two settings controlled goal checks: ``governance.goal_validation_interval``
(read by the AgentLoop's alignment critic, default 2) and
``logic_gate.reasoning_config.goal_validation_interval`` (read by the step
engine's GoalGuard, as 0 when absent — so off, though the schema said 2), and
both were in the builder. ``GoalGuard``, ``MetaReviewer`` and ``AlignmentCritic``
remained as shims; only GoalGuard had a caller, and only its RETRY branch could
fire. Now governance's is the setting, the step-level check and the shims are
deleted, and the old key still saves (accepted, dropped).
"""
from __future__ import annotations

import importlib.util
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[2]


def test_the_shims_are_gone():
    for module in ("src.ai.planning.goal_guard", "src.ai.core.meta_review"):
        assert importlib.util.find_spec(module) is None, module
    engine = (BACKEND / "src/ai/core/step_engine.py").read_text(encoding="utf-8")
    assert "GoalGuard(" not in engine and "__alignment_correction__" not in engine


def test_the_old_key_still_saves_and_governance_is_the_setting():
    from src.ai.schemas.entity import HierarchicalEntityCreateRequest
    from src.ai.schemas.governance import Governance
    from src.ai.schemas.reasoning import ReasoningConfig
    from src.ai.schemas.strict_keys import unknown_keys

    payload = {"name": "x", "type": "AGENT", "logic_gate": {"reasoning_config": {"goal_validation_interval": 3}},
               "governance": {"goal_validation_interval": 4}}
    assert unknown_keys(HierarchicalEntityCreateRequest, payload) == []
    assert "goal_validation_interval" not in ReasoningConfig.model_fields
    assert Governance(goal_validation_interval=4).goal_validation_interval == 4


def test_the_supervisor_has_no_legacy_switch():
    from src.ai.planning.critic_pipeline import RealCriticPipeline
    pipe = RealCriticPipeline(db=None, llm_router=None, cortex_service=None,
                              config={"supervisor_v2_enabled": False})
    assert pipe._supervisor_v2 is not None
