"""Phase 11 enrichment layer for the Document Factory seed.

The original Document Factory entity definitions (``actions_*.py``, ``skills.py``,
``agents.py`` and the PROCESS payload in ``create_doc_entities.py``) were authored
against the *pre-Phase-11* kernel. This module enriches every payload so a single
run of the PROCESS exercises the new agent kernel.

WHERE PHASE 11 CONFIG ACTUALLY LIVES
------------------------------------
This was the trap that the first version of this file fell into: the entity
create/update schema (``src/ai/schemas/entity.py``) is a *closed* Pydantic model.
It has **no** ``extra = "allow"``, so any key that is not a declared schema field
is **silently dropped on create** (verified against a live entity GET). That
killed an earlier design that hung config off invented keys like
``feature_flag_overrides``, ``logic_gate.task_class``, ``governance.budget``,
``capabilities.memory.domains`` and ``dynamic_planning.n_candidates`` — none of
those are schema fields, so none of them persisted.

The kernel reads Phase 11 per-entity config from exactly two real channels:

1. ``metadata_extensions.feature_flags`` — the per-entity tier of the feature-flag
   resolver (``core/feature_flags.py`` ``_read_entity_extras``; gate at
   ``core/execution_engine.py`` ``execute_run`` reads it via ``entity_extras``).
   Accepts flat keys (``"agent_loop.enabled": true``).
2. ``metadata_extensions.task_class`` — the explicit bandit task-class override
   (``memory/task_classifier.py`` ``_entity_meta_task_class``).

Plus one ordinary schema field:

3. ``logic_gate.reasoning_config.reasoning_mode`` — a real enum field, persists
   normally; selects the Track-2 reasoning module.

Everything else Phase 11 added is **already ON by global default** in
``core/feature_flags.py`` (critic v2, meta-review v2, bandit, planner v2 +
invariants + judge, memory v2 + scope policy + dreaming, tool cost/resilience v2).
We additionally pin all of them in the per-entity ``feature_flags`` block so a
test run is reproducible regardless of any company/global DB overrides — and
because the loop re-resolves every flag with ``entity_extras`` per entity, the
pin is honoured on the parent and on each child invocation.

Budget envelopes are covered by the existing ``governance.max_cost_usd`` +
``governance.timeout_ms`` on each entity (``core/budget.py`` ``Budget.from_governance``
builds the token/iteration axes from sane defaults). EXPERIMENTAL-tool gating
(Track 8) is registry/admin-scoped and cannot be expressed in a seed payload.

``create_doc_entities.py`` calls :func:`enrich_payload` on each payload before it
is POSTed.
"""
from __future__ import annotations

from typing import Any, Dict

# ---------------------------------------------------------------------------
# 1. Feature-flag overrides — written to metadata_extensions.feature_flags on
#    EVERY entity (parent + every child re-resolve flags from their own config).
#    The two master switches default OFF; the rest default ON but are pinned for
#    reproducibility.
# ---------------------------------------------------------------------------
FEATURE_FLAG_OVERRIDES: Dict[str, bool] = {
    # master canary switches (default OFF) — flip ON for this hierarchy
    "agent_loop.enabled": True,
    "meta_agent.board_routing": True,
    # critic pipeline v2
    "critic_pipeline.v2_enabled": True,
    "critic_pipeline.pre_critic_enabled": True,
    "critic_pipeline.different_model_critic": True,
    "critic_pipeline.calibration_enabled": True,
    # meta-review + bandit
    "meta_review.v2_enabled": True,
    "meta_review.fast_path_enabled": True,
    "bandit.enabled": True,
    # planner v2
    "planner.v2_enabled": True,
    "planner.invariants_enforced": True,
    "planner.judge_enabled": True,
    "planner.priors_enabled": True,
    # memory v2
    "memory.v2_canonical": True,
    "memory.scope_policy_enforced": True,
    "memory.dreaming_outcome_trigger": True,
    # tool + cost
    "tools.cost_resolver_v2_enabled": True,
    "tools.resilience_v2_enabled": True,
    # meta-agent downstream gates (ready for the board flip)
    "meta_agent.spec_critic_required": True,
    "meta_agent.draft_lifecycle": True,
}

# ---------------------------------------------------------------------------
# 2. Reasoning mode per entity (covers all four Phase 11 modes).
#    PROCESS  -> TREE_OF_THOUGHTS  (explore routing alternatives)
#    agents   -> REFLECTION / REACT
#    skills   -> REACT (tool-executing) / CHAIN_OF_THOUGHT (read/validate)
#    actions  -> REACT / CHAIN_OF_THOUGHT
# ---------------------------------------------------------------------------
REASONING_MODE_BY_KEY: Dict[str, str] = {
    "doc_factory_process": "TREE_OF_THOUGHTS",
    "docx_document_agent": "REFLECTION",
    "pptx_presentation_agent": "REFLECTION",
    "xlsx_spreadsheet_agent": "REACT",
    "pdf_document_agent": "REACT",
    "doc_qa_delivery_agent": "CHAIN_OF_THOUGHT",
}

# Keyword fallbacks for skills/actions: reading / validating / inspecting work
# is deliberative (CoT); everything else actively drives tools (ReAct).
_COT_KEYWORDS = (
    "reader", "validator", "validate", "analyz", "verify", "extract",
    "detect", "visual_qa", "visual-qa", "content_validation", "qa_pipeline",
    "qa-pipeline",
)


def _resolve_reasoning_mode(key: str) -> str:
    if key in REASONING_MODE_BY_KEY:
        return REASONING_MODE_BY_KEY[key]
    lowered = key.lower()
    if any(kw in lowered for kw in _COT_KEYWORDS):
        return "CHAIN_OF_THOUGHT"
    return "REACT"


# ---------------------------------------------------------------------------
# 3. Bandit task class — per document family. Bandit arms are keyed
#    per-(entity_id, task_class), so a consistent class per family lets the
#    bandit accumulate plan-style statistics across runs.
# ---------------------------------------------------------------------------
def _resolve_task_class(key: str) -> str:
    if key.startswith("doc_factory"):
        return "document_orchestration"
    if key.startswith("docx"):
        return "docx_authoring"
    if key.startswith("pptx"):
        return "pptx_design"
    if key.startswith("xlsx"):
        return "xlsx_modeling"
    if key.startswith("pdf"):
        return "pdf_processing"
    return "document_qa"  # doc_qa_*, doc_content_*, doc_archive_*


def enrich_payload(key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Mutate *payload* in place with Phase 11 config and return it.

    Only writes to channels the kernel actually reads (see module docstring).
    """
    # 1 + 3. Per-entity feature flags + bandit task class via metadata_extensions.
    meta = payload.setdefault("metadata_extensions", {})
    if not isinstance(meta, dict):
        meta = {}
        payload["metadata_extensions"] = meta
    ff = dict(meta.get("feature_flags") or {})
    ff.update(FEATURE_FLAG_OVERRIDES)
    meta["feature_flags"] = ff
    meta["task_class"] = _resolve_task_class(key)
    # human-readable breadcrumb for the canary (ignored by the kernel)
    meta["phase11_seed"] = True

    # 2. Reasoning mode (a real schema field).
    logic_gate = payload.setdefault("logic_gate", {})
    rc = logic_gate.setdefault("reasoning_config", {})
    rc["reasoning_mode"] = _resolve_reasoning_mode(key)

    return payload
