#!/usr/bin/env python3
"""
doc-factory-lite — lean single-agent replacement for doc-factory-process.

See ``docs/phase11/DOC_FACTORY_REDESIGN.md`` for the why. In one sentence:
the 50-entity, 4-level doc-factory hierarchy multiplies LLM calls on top of the
Phase-11 loop; this collapses it to ONE flat AGENT with a deterministic
``outline → generate → validate → finalize`` plan (one lightweight planning
step, then build), in-sandbox validation (no whole-file context bloat), an
enforced cost cap, and exactly ONE registered artifact.

Usage:
    python create_lite.py                 # create the entity (idempotent-ish)
    python create_lite.py --cleanup       # delete the previously-created entity
    python create_lite.py --request "..." # create (if needed) + trigger a run

The script reuses the sibling SeedDocumentFactory's APIClient and the Phase-11
``enrich_payload`` helper so flag/reasoning parity is identical to the existing
seed.

SCHEMA NOTES (entity create is a *closed* Pydantic model — unknown keys are
silently dropped):
  * system prompt lives under ``identity`` (Optional[Any]), NOT ``prompts``.
  * critic cadence (goal/meta-review interval) is read by the critic pipeline
    from ``governance`` with defaults 2 / 3 — but Governance is a closed schema
    without those fields, so we rely on the favourable defaults rather than
    writing keys that would be dropped. ``reasoning_config.goal_validation_interval``
    IS a real field and is set to 2.
  * ``review_mechanism.critic_model_override`` is read by the kernel but is NOT a
    declared schema field, so it cannot be set from a seed payload (documented
    limitation — would need an admin/registry channel).
  * retry bounding uses ``logic_gate.retry_policy.max_retries`` (real field);
    ``review_mechanism.max_retries`` does not exist.
  * ``context_policy`` nests under ``logic_gate`` and ``type`` must be one of
    FULL | LAST_N | SLIDING_WINDOW | EXPLICIT.
"""
from __future__ import annotations

import json
import os
import sys

# Reuse the existing SeedDocumentFactory APIClient + Phase-11 enrichment.
_SIBLING = os.path.join(os.path.dirname(__file__), "..", "SeedDocumentFactory")
sys.path.insert(0, os.path.abspath(_SIBLING))
sys.path.insert(0, os.path.dirname(__file__))

from config import APIClient          # noqa: E402  (sibling seed)
from phase11 import enrich_payload    # noqa: E402  (sibling seed)

_IDS_PATH = os.path.join(os.path.dirname(__file__), "entity_ids.json")
_ENTITY_KEY = "doc_factory_lite"


# ---------------------------------------------------------------------------
# Entity payload
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a single-pass document generator. Produce ONE final, "
    "publication-quality document (xlsx / docx / pptx / pdf) from the request, "
    "planned, validated, and saved exactly once, then STOP.\n\n"
    "## Workflow (4 steps, in order, no more)\n"
    "1. OUTLINE (plan first — do NOT write code here) — analyse the request and "
    "produce a concise structured SPEC in text: target format, the sheets/slides/"
    "sections, the columns/fields, formulas or calculations needed, and the "
    "styling. Think before building. Output ONLY the outline text; do NOT call "
    "any tool and do NOT create files in this step.\n"
    "2. GENERATE — following the OUTLINE, write code that creates the file in a "
    "relative `scratch/` directory (create it first with os.makedirs('scratch', "
    "exist_ok=True); e.g. `scratch/output.xlsx`). Files under `scratch/` are NOT "
    "auto-registered. Do NOT save/register the file in this step.\n"
    "3. VALIDATE — IN-SANDBOX: load the scratch file and assert it is structurally "
    "valid with zero formula errors (no #REF!, #DIV/0!, #VALUE!). Return a SHORT "
    "pass/fail verdict ONLY — NEVER print the file's contents back into the "
    "conversation (that is what made the old design cost $15+).\n"
    "4. FINALIZE — only when validation passes, call the `document_save` tool "
    "EXACTLY ONCE with source_path set to the scratch file (a sandbox-relative "
    "path like 'scratch/output.xlsx' is accepted), a descriptive filename, the "
    "format, and purpose='final'. That single call registers the one and only "
    "artifact.\n\n"
    "## Hard rules\n"
    "- Plan in step 1 BEFORE writing any code.\n"
    "- Call document_save EXACTLY ONCE, only in the FINALIZE step.\n"
    "- Do NOT regenerate a file that already validates.\n"
    "- Do NOT write probe/test files (e.g. test.xlsx) anywhere that gets saved.\n"
    "- Do NOT read a generated file's full contents back into context.\n"
    "- Prefer formulas over hard-coded values; apply clean, professional formatting."
)

DOC_FACTORY_LITE = {
    "name": "doc-factory-lite",
    "display_name": "📄 Document Factory (Lite)",
    "description": (
        "Lean single-agent document generator: deterministic "
        "outline→generate→validate→finalize pass, in-sandbox validation, enforced "
        "cost cap, exactly one final artifact. A/B alternative to doc-factory-process."
    ),
    "goal": (
        "Produce ONE final, publication-quality document (xlsx/docx/pptx/pdf) "
        "from a single request, validated and saved exactly once. Then stop."
    ),
    "type": "AGENT",
    "version": "1.0.0",
    "status": "ACTIVE",
    "tags": ["doc-factory", "lite", "single-agent"],

    # System prompt + behaviour live under identity (Persona-shaped).
    "identity": {
        "system_prompt": SYSTEM_PROMPT,
        "behavioral_constraints": [
            "Plan/outline before writing any code",
            "Write working files only under scratch/",
            "Validate in-sandbox; never echo file contents into context",
            "Call document_save exactly once, only in the finalize step",
            "Stop as soon as the file validates and is saved",
        ],
    },

    # 4 deterministic steps: a single lightweight planning/outline step (the
    # user's "it should plan, not jump straight to creating a file" feedback)
    # followed by generate → validate → finalize. ONE planning step, not the old
    # 4 THOUGHT steps. Dynamic planning stays OFF so the planner cannot
    # re-decompose into the 8-step monster.
    "planning": {
        "static_plan": {
            "enabled": True,
            "fallback_behavior": "STRICT",
            "steps": [
                {
                    "step_id": "outline", "order": 1, "name": "Analyze & outline",
                    "type": "THOUGHT", "required": True,
                    "target": {
                        "prompt_template": (
                            "PLAN FIRST — do NOT write code or call any tool. "
                            "Analyze the request and output a concise structured "
                            "SPEC in text: target format (xlsx/docx/pptx/pdf), the "
                            "sheets/slides/sections, columns/fields, formulas or "
                            "calculations, and styling. Request:\n\n{{input}}"
                        ),
                    },
                },
                {
                    "step_id": "generate", "order": 2, "name": "Generate document",
                    "type": "ACTION", "required": True,
                    "target": {
                        "tool_id": "sandbox_code",
                        "prompt_template": (
                            "Following this OUTLINE, write code that creates the "
                            "document under a relative scratch/ directory "
                            "(os.makedirs('scratch', exist_ok=True) first). Do NOT "
                            "save/register it here.\n\nOUTLINE:\n{{outline}}\n\n"
                            "Original request:\n{{input}}"
                        ),
                        "input_dependencies": ["outline"],
                    },
                },
                {
                    "step_id": "validate", "order": 3, "name": "Validate in-sandbox",
                    "type": "ACTION", "required": True,
                    "target": {
                        "tool_id": "sandbox_code",
                        "prompt_template": (
                            "Load the scratch/ output and assert zero structural/"
                            "formula errors. Return a SHORT pass/fail verdict only "
                            "— do NOT print file contents."
                        ),
                        "input_dependencies": ["generate"],
                    },
                },
                {
                    "step_id": "finalize", "order": 4, "name": "Save final artifact",
                    "type": "ACTION", "required": True,
                    "target": {
                        "tool_id": "document_save",
                        "prompt_template": (
                            "Call document_save EXACTLY ONCE: source_path = the "
                            "scratch file you created (a relative path like "
                            "'scratch/<name>.<ext>' is accepted), a descriptive "
                            "filename, the format, and purpose='final'. This is the "
                            "ONLY save in the whole run."
                        ),
                        "input_dependencies": ["validate"],
                    },
                },
            ],
        },
        "dynamic_planning": {"enabled": False},
    },

    "capabilities": {
        "tools": [{"tool_id": "sandbox_code"}, {"tool_id": "document_save"}],
        "memory": {
            "enabled": True, "mode": "CORTEX", "memory_scope": "INTELLIGENCE_ONLY",
            "cortex_config": {"auto_checkpoint": True, "context_budget_pct": 25},
        },
    },

    "logic_gate": {
        "reasoning_config": {
            "reasoning_mode": "REACT",
            # GoalGuard OFF (0): it re-executes a step whenever the output looks
            # "off-goal", but for a multi-step deterministic plan the early steps
            # (outline) legitimately aren't the final document, so it just churns.
            "goal_validation_interval": 0,
        },
        "retry_policy": {"max_retries": 1},
        # LLM review/critic OFF. The in-sandbox `validate` step IS the quality
        # gate (it asserts zero formula/structural errors deterministically). An
        # LLM critic on top flags every pre-document iteration as INCOMPLETE/
        # WRONG_FORMAT and corrective-retries the planning step ~10× — the
        # doc-factory-lite churn. See also feature_flags.critic_pipeline below.
        "review_mechanism": {"enabled": False},
        # Cap context so ReAct turns don't accumulate full tool dumps. The primary
        # bloat fix is in-sandbox validation (system prompt); this is a backstop.
        "context_policy": {
            "type": "FULL", "summarize_threshold": 8000,
            "preserve_keys": ["request_type", "final_artifact"],
        },
    },

    # max_cost_usd is now ENFORCED on the run (see DOC_FACTORY_REDESIGN.md §5.1 /
    # ExecutionEngine._enforce_cost_cap), so this is a real ceiling, not decoration.
    "governance": {
        "timeout_ms": 300000,
        "max_cost_usd": 2.00,
        "max_recursion_depth": 1,
        "execution_limits": {"max_recursion_depth": 1, "max_tool_calls": 10},
    },

    "observability": {"log_thoughts": True},
}


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def _save_id(entity_id: str) -> None:
    with open(_IDS_PATH, "w") as f:
        json.dump({_ENTITY_KEY: entity_id}, f, indent=2)


def _load_id() -> str | None:
    if not os.path.exists(_IDS_PATH):
        return None
    try:
        with open(_IDS_PATH) as f:
            return json.load(f).get(_ENTITY_KEY)
    except (json.JSONDecodeError, OSError):
        return None


def _build_payload() -> dict:
    # enrich_payload pins the Phase-11 feature flags (incl. agent_loop.enabled)
    # in metadata_extensions and sets reasoning_mode for flag/reasoning parity
    # with the existing seed. We then override task_class to a document family.
    payload = enrich_payload(_ENTITY_KEY, dict(DOC_FACTORY_LITE))
    meta = payload.setdefault("metadata_extensions", {})
    meta["task_class"] = "document_authoring"

    # enrich_payload pins the WHOLE Phase-11 critic/meta-review stack ON (it was
    # built as a canary that exercises every kernel feature). For a lean,
    # deterministic document pipeline that is actively harmful: the post-critic
    # flags every pre-document iteration REVISE/[INCOMPLETE,WRONG_FORMAT] and
    # corrective-retries the planning step until the retry/iteration cap, and the
    # supervisor recommends REPLAN every iteration — burning ~10× the tokens and
    # never advancing past step 1. We turn the critic stack OFF here; the
    # in-sandbox `validate` step is the quality gate instead.
    ff = meta.setdefault("feature_flags", {})
    ff.update({
        "critic_pipeline.v2_enabled": False,
        "critic_pipeline.pre_critic_enabled": False,
        "critic_pipeline.different_model_critic": False,
        "meta_review.v2_enabled": False,
    })
    return payload


def upsert(client: APIClient) -> str:
    """Create the entity, or UPDATE it in place if it already exists.

    Re-running the script re-applies the latest payload (plan/prompt/governance)
    so config changes take effect without a manual --cleanup first.
    """
    payload = _build_payload()
    existing = _load_id()

    print("=" * 64)
    if existing:
        print("🔄 Updating doc-factory-lite (single flat agent)")
        print("=" * 64)
        data = client.update_entity(existing, payload)
    else:
        print("📄 Creating doc-factory-lite (single flat agent)")
        print("=" * 64)
        data = client.create_entity(payload)
    _save_id(data["id"])
    print(f"\n  Saved entity id → {_IDS_PATH}")
    return data["id"]


def cleanup(client: APIClient) -> None:
    eid = _load_id()
    if not eid:
        print("  ⚠️  No saved doc-factory-lite id to delete.")
        return
    client.delete_entity(eid)
    try:
        os.remove(_IDS_PATH)
    except OSError:
        pass


def trigger(client: APIClient, entity_id: str, request_text: str) -> None:
    print("\n" + "=" * 64)
    print("🚀 Triggering doc-factory-lite execution")
    print("=" * 64)
    print(f"Request: {request_text[:160]}{'…' if len(request_text) > 160 else ''}")
    # /ai/execute is strict: {entity_id, input_data} only (422 otherwise).
    resp = client.session.post(
        f"{client.base_url}/ai/execute",
        json={"entity_id": entity_id, "input_data": {"input": request_text}},
    )
    if resp.status_code in (200, 201, 202):
        out = resp.json()
        print(f"  ✅ Run queued: {out.get('id')} (status={out.get('status')})")
    else:
        print(f"  ❌ Trigger failed: {resp.status_code} — {resp.text[:400]}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Create/trigger doc-factory-lite")
    parser.add_argument("--cleanup", action="store_true", help="Delete the entity")
    parser.add_argument("--request", type=str, default=None,
                        help="Create (if needed) and trigger a run with this request")
    args = parser.parse_args()

    client = APIClient()
    client.verify_auth()

    if args.cleanup:
        cleanup(client)
        return

    entity_id = upsert(client)

    if args.request:
        trigger(client, entity_id, args.request)
    else:
        print("\n  Done. Trigger a run with:")
        print('    python create_lite.py --request '
              '"create an insurance company balance sheet template"')


if __name__ == "__main__":
    main()
