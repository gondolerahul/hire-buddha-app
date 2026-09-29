"""Entity configuration rejects keys it would ignore (PO-09); runtime knobs are declared (EP-11, PC-16).

Pydantic dropped undeclared keys silently, so a typo — or a real setting the
schema never declared — saved with 200 OK and did nothing. The API's create and
update payloads now 422 on any undeclared key, naming its path. The knobs the
runtime reads are declared, so they can be set at all.
"""
from __future__ import annotations

import copy
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from src.ai.schemas import (
    HierarchicalEntityCreate,
    HierarchicalEntityCreateRequest,
    HierarchicalEntityResponse,
    HierarchicalEntityUpdateRequest,
)
from src.ai.schemas.strict_keys import unknown_keys

# The shape the entity builder sends on save (EntityConfigurationTabs.handleSave),
# captured from the running app with long strings shortened.
BUILDER_PAYLOAD = {
    "name": "research-writer", "display_name": "research-writer - Writer", "type": "SKILL",
    "description": "Writes the report", "goal": "Write a report", "version": "1.0.0",
    "status": "ACTIVE", "tags": ["deep-research-v2"],
    "identity": {"role": "Writer", "bio": "Writes", "system_prompt": "You write reports.",
                 "personality": {"tone": "formal", "verbosity": "moderate", "empathy_level": 0.5,
                                 "humor_level": 0.1, "formality": "formal", "decision_confidence": 0.8},
                 "behavioral_constraints": [], "few_shot_examples": []},
    "logic_gate": {
        "reasoning_config": {"task_type": "text_generation", "temperature": 0.4, "top_p": 1,
                             "max_tokens": 16000, "reasoning_mode": "REACT", "model_name": "gemini-2.5-flash",
                             "execution_mode": "AUTONOMOUS", "goal_validation_interval": 2,
                             "confidence_threshold": 0.85, "max_replanning_attempts": 2,
                             "self_reflection_enabled": True},
        "retry_policy": {"max_retries": 2, "backoff_strategy": "EXPONENTIAL", "backoff_multiplier": 2},
        "review_mechanism": {"enabled": False, "review_prompt": "", "review_system_prompt": "Review.",
                             "on_failure": "RETRY", "success_criteria": []},
        "context_policy": {"type": "FULL", "n": None, "max_chars": None, "summarize_threshold": 12000,
                           "preserve_keys": []},
    },
    "planning": {
        "static_plan": {"enabled": True, "fallback_behavior": "ADAPTIVE", "steps": [
            {"step_id": "step_1", "order": 1, "name": "Draft", "description": "Draft it", "type": "ACTION",
             "target": {"prompt_template": "Write {{input}}", "input_dependencies": []}, "required": True},
            {"step_id": "step_2", "order": 2, "name": "DOCX", "description": "Convert", "type": "TOOL_CALL",
             "target": {"tool_id": "docx_generator", "input_dependencies": ["step_1"]}, "required": True},
        ]},
        "dynamic_planning": {"enabled": False, "planning_prompt": "", "planning_system_prompt": "Plan.",
                             "reconciliation_strategy": "HYBRID",
                             "allowed_deviations": {"can_add_steps": True, "can_skip_optional_steps": True,
                                                    "can_reorder_steps": False, "can_change_tools": False}},
        "loop_control": {"max_iterations": 1, "iteration_context_mode": "FULL_HISTORY"},
    },
    "capabilities": {
        "tools": [{"tool_id": "docx_generator", "usage": "AUTONOMOUS"}],
        "memory": {"enabled": True, "mode": "CORTEX", "episodic_memory_count": 10,
                   "semantic_search_enabled": True, "semantic_top_k": 5,
                   "cortex_config": {"max_children": 12, "page_size_tokens": 8000, "context_budget_pct": 40,
                                     "auto_checkpoint": True, "resume_enabled": True}},
        "context_engineering": {"context_sources": [], "inject_episodic_memory": True,
                                "inject_semantic_context": True, "inject_cortex_viewport": True,
                                "no_truncation": True},
    },
    "governance": {"max_cost_usd": 1, "timeout_ms": 180000, "execution_limits": {"max_recursion_depth": 5},
                   "hitl_checkpoints": [], "checkpoint_every_n_steps": 3},
    "io_contract": {"input_schema": {"type": "object", "properties": {}},
                    "output_schema": {"type": "object", "properties": {}}},
    "observability": {"log_level": "INFO", "log_thoughts": True, "track_cost": True},
    "hierarchy": {"children": [], "is_atomic": False},
}


def _with(path: str, value):
    """BUILDER_PAYLOAD with one key set at a dotted path (``[i]`` indexes lists)."""
    payload = copy.deepcopy(BUILDER_PAYLOAD)
    node = payload
    parts = path.replace("[", ".[").split(".")
    for part in parts[:-1]:
        node = node[int(part[1:-1])] if part.startswith("[") else node.setdefault(part, {})
    node[parts[-1]] = value
    return payload


def test_the_builders_payload_is_accepted():
    assert unknown_keys(HierarchicalEntityCreate, BUILDER_PAYLOAD) == []
    HierarchicalEntityCreateRequest.model_validate(BUILDER_PAYLOAD)
    HierarchicalEntityUpdateRequest.model_validate(BUILDER_PAYLOAD)


@pytest.mark.parametrize("path", [
    "prompts",                                             # the seed-author trap: prompts go under identity
    "logic_gate.retry_polcy",
    "logic_gate.reasoning_config.temprature",
    "planning.static_plan.steps[1].target.tool",
    "capabilities.memory.enabeld",
    "governance.meta_review_enabled",                      # nothing reads it
])
def test_an_unknown_key_is_rejected_with_its_path(path):
    payload = _with(path, 1)
    assert unknown_keys(HierarchicalEntityCreate, payload) == [path]
    for model in (HierarchicalEntityCreateRequest, HierarchicalEntityUpdateRequest):
        with pytest.raises(ValidationError) as err:
            model.model_validate(payload)
        assert path in str(err.value)


def test_a_typo_inside_a_hitl_checkpoint_is_caught():
    payload = _with("governance.hitl_checkpoints", [{"trigger_type": "BEFORE_STEP", "step_ref": "Draft",
                                                     "timeout": 60000}])
    assert unknown_keys(HierarchicalEntityCreate, payload) == ["governance.hitl_checkpoints[0].timeout"]


def test_the_runtime_knobs_are_declared_and_kept():
    payload = copy.deepcopy(BUILDER_PAYLOAD)
    payload["governance"].update({"critic_cost_share_pct": 0.35, "goal_validation_interval": 4,
                                  "meta_review_interval": 5, "max_concurrent_children": 2})
    payload["logic_gate"]["review_mechanism"]["critic_model_override"] = "gemini-2.5-pro"
    dumped = HierarchicalEntityCreateRequest.model_validate(payload).model_dump(mode="json")
    gov = dumped["governance"]
    assert (gov["critic_cost_share_pct"], gov["goal_validation_interval"], gov["meta_review_interval"],
            gov["max_concurrent_children"]) == (0.35, 4, 5, 2)
    assert dumped["logic_gate"]["review_mechanism"]["critic_model_override"] == "gemini-2.5-pro"


def test_declared_defaults_equal_the_runtime_fallbacks():
    """An entity that sets none of them behaves exactly as before they were declared."""
    gov = HierarchicalEntityCreate.model_validate(
        {"name": "x", "type": "AGENT", "governance": {}}).model_dump()["governance"]
    # agent_loop: gov.get("critic_cost_share_pct", 0.20) / ("goal_validation_interval", 2) /
    # ("meta_review_interval", 3); child_entity: None -> DEFAULT_MAX_CONCURRENT_CHILDREN.
    assert (gov["critic_cost_share_pct"], gov["goal_validation_interval"], gov["meta_review_interval"],
            gov["max_concurrent_children"]) == (0.20, 2, 3, None)


def test_stored_entities_with_old_keys_still_read_back():
    """Strictness is for requests only; a stored stray key must not break the Entity Library."""
    now = "2026-09-29T00:00:00"
    stored = {**BUILDER_PAYLOAD, "id": str(uuid.uuid4()), "company_id": str(uuid.uuid4()),
              "parent_id": None, "created_at": now, "updated_at": now,
              "governance": {**BUILDER_PAYLOAD["governance"], "some_retired_key": True}}
    HierarchicalEntityResponse.model_validate(stored)


@pytest.mark.asyncio
async def test_the_api_returns_422_naming_the_key(monkeypatch):
    from src.ai import router as ai_router_module
    from src.auth.dependencies import get_current_user
    from src.common.database import get_db

    async def reached_service(self, *args, **kwargs):
        raise HTTPException(status_code=418, detail="validation passed")

    monkeypatch.setattr(ai_router_module.AIService, "create_entity", reached_service)
    monkeypatch.setattr(ai_router_module.AIService, "update_entity", reached_service)
    app = FastAPI()
    app.include_router(ai_router_module.router, prefix="/api/v1")

    async def _user():
        return SimpleNamespace(id=uuid.uuid4(), role="tenant_admin", company_id=uuid.uuid4())

    async def _db():
        yield None

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    typo = _with("logic_gate.retry_polcy", {"max_retries": 5})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        created = await c.post("/api/v1/ai/entities", json=typo)
        updated = await c.put(f"/api/v1/ai/entities/{uuid.uuid4()}", json={"governance": {"max_cost": 2}})
        valid = await c.post("/api/v1/ai/entities", json=BUILDER_PAYLOAD)
    assert created.status_code == 422 and "logic_gate.retry_polcy" in created.text
    assert updated.status_code == 422 and "governance.max_cost" in updated.text
    assert valid.status_code == 418  # the valid payload reached the service
