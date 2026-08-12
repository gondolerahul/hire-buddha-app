"""
meta_spec_critic — Phase 11 Track 5 spec-quality critic tool.

Reviews a draft :class:`HierarchicalEntity` spec for failure modes
*before* it can be promoted. Uses:

  * The Meta-Agent's :class:`MetaIntelligenceTree` to surface known
    anti-patterns relevant to the spec's type / tags.
  * A *different* LLM model from the Architect (Phase 11 Track 3's
    ``resolve_critic_model`` heuristic) so this is a true second opinion.

Input (JSON)::

    {
      "mode": "review_spec",
      "spec": <full HierarchicalEntity payload>,
      "search_top_k": [<top reuse candidates from meta_registry_search>],
      "platform_manifest_hash": "<for cache key>"
    }

Output (JSON)::

    {
      "verdict": "PASS|REVISE|BLOCK",
      "concerns": [
        {"severity": "low|med|high|critical",
         "category": "cost|cycles|prompt|tools|governance|io_contract|hallucination_risk",
         "issue": "...",
         "fix_suggestion": "...",
         "blocks_promotion": true|false}
      ],
      "rules_referenced": ["<intelligence_rule_node_id>", ...]
    }

Side effects:
  * Novel concerns with severity ≥ ``med`` are written back into the
    company's MetaIntelligenceTree ``📏 Architecture Anti-Patterns``
    section so the next spec the Critic reviews benefits from this
    one's lessons.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional
from uuid import UUID

from src.ai.tools.base import Tool

logger = logging.getLogger(__name__)


_SEVERITY_RANK = {"low": 0, "med": 1, "high": 2, "critical": 3}


def _build_system_prompt(anti_patterns: list[Any]) -> str:
    head = (
        "You are a Staff Engineer reviewing an AI agent specification.\n"
        "Assume the Architect is overconfident. Enumerate every plausible "
        "failure mode. For each, cite a concrete input that triggers it, "
        "an expected pathology, and the cheapest fix.\n"
        "If you cannot find ≥3 issues, you are not looking hard enough.\n"
    )
    if anti_patterns:
        head += "\nKnown anti-patterns to check:\n"
        for a in anti_patterns:
            text = getattr(a, "text", None) or str(a)
            head += f"  - {str(text)[:240]}\n"
    head += (
        "\nReturn JSON only with this shape:\n"
        '{"verdict":"PASS|REVISE|BLOCK","concerns":['
        '{"severity":"low|med|high|critical",'
        '"category":"cost|cycles|prompt|tools|governance|io_contract|hallucination_risk",'
        '"issue":"...","fix_suggestion":"...","blocks_promotion":true|false}'
        '],"rules_referenced":[]}'
    )
    return head


def _build_user_prompt(spec: dict[str, Any], search_top_k: list[Any]) -> str:
    # Truncate the spec safely for the prompt — keep the structure but
    # cap large nested fields.
    spec_blob = json.dumps(spec, default=str)
    if len(spec_blob) > 8000:
        spec_blob = spec_blob[:8000] + "\n…(spec truncated)"
    candidates_block = ""
    if search_top_k:
        try:
            candidates_block = (
                "\n## Existing candidates (top-3 from registry search):\n"
                + json.dumps(search_top_k[:3], default=str)[:1200]
            )
        except Exception:
            candidates_block = ""
    return (
        "## Draft spec under review:\n"
        f"{spec_blob}\n"
        f"{candidates_block}\n"
        "Now produce the JSON verdict."
    )


def _normalise_verdict(parsed: dict[str, Any]) -> dict[str, Any]:
    verdict = str(parsed.get("verdict", "REVISE")).upper()
    if verdict not in {"PASS", "REVISE", "BLOCK"}:
        verdict = "REVISE"
    concerns_in = parsed.get("concerns") or []
    concerns: list[dict] = []
    for c in concerns_in:
        if not isinstance(c, dict):
            continue
        sev = str(c.get("severity", "low")).lower()
        if sev not in _SEVERITY_RANK:
            sev = "low"
        cat = str(c.get("category", "prompt"))
        issue = str(c.get("issue", ""))[:300]
        fix = str(c.get("fix_suggestion", ""))[:300]
        blocks = bool(c.get("blocks_promotion", False))
        if not issue:
            continue
        concerns.append({
            "severity": sev,
            "category": cat,
            "issue": issue,
            "fix_suggestion": fix,
            "blocks_promotion": blocks,
        })
    # Defensive override: if any concern blocks_promotion, escalate verdict to BLOCK.
    if any(c["blocks_promotion"] for c in concerns) and verdict != "BLOCK":
        verdict = "BLOCK"
    return {
        "verdict": verdict,
        "concerns": concerns,
        "rules_referenced": list(parsed.get("rules_referenced") or []),
    }


class MetaSpecCriticTool(Tool):
    name = "meta_spec_critic"
    description = (
        "Reviews a draft HierarchicalEntity spec for failure modes BEFORE "
        "the Promoter can flip the entity to ACTIVE. Input JSON: "
        "{'mode':'review_spec','spec':<spec>,'search_top_k':[...], "
        "'platform_manifest_hash':'...'}. Returns JSON: "
        "{'verdict':'PASS|REVISE|BLOCK','concerns':[...],'rules_referenced':[...]}."
    )

    async def run(self, input_data: str) -> str:
        return json.dumps({
            "error": "meta_spec_critic requires execution context. Use run_with_context().",
        })

    async def run_with_context(
        self, input_data: str, context: Optional[dict] = None,
    ) -> str:
        context = context or {}
        company_id = context.get("company_id")
        if not company_id:
            return json.dumps({"error": "Missing company_id in execution context"})

        try:
            params = json.loads(input_data) if isinstance(input_data, str) else input_data
        except Exception:
            return json.dumps({
                "error": "Invalid JSON; expected an object with 'spec'.",
            })

        spec = params.get("spec") or {}
        if not isinstance(spec, dict):
            return json.dumps({"error": "'spec' must be a JSON object."})
        search_top_k = params.get("search_top_k") or []

        try:
            return await self._review(company_id, spec, search_top_k, context)
        except Exception as exc:                                            # noqa: BLE001
            logger.exception("meta_spec_critic failed")
            return json.dumps({
                "verdict": "REVISE",
                "concerns": [{
                    "severity": "med",
                    "category": "prompt",
                    "issue": f"spec_critic tool failed: {type(exc).__name__}",
                    "fix_suggestion": "Retry or fall back to validator-only path.",
                    "blocks_promotion": False,
                }],
                "rules_referenced": [],
            })

    async def _review(
        self,
        company_id: Any,
        spec: dict[str, Any],
        search_top_k: list[Any],
        context: dict[str, Any],
    ) -> str:
        from src.ai.llm.router import LLMRouter
        from src.ai.meta.meta_intelligence_tree import MetaIntelligenceTree
        from src.ai.planning.critic_pipeline import resolve_critic_model
        from src.ai.shared.json_utils import parse_json_object
        from src.common.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            meta_tree = MetaIntelligenceTree(
                db=db,
                company_id=UUID(str(company_id)) if not isinstance(company_id, UUID) else company_id,
            )
            anti = await meta_tree.query_anti_patterns(
                entity_type=str(spec.get("type", "")) or None,
                tags=list(spec.get("tags") or []),
                top_k=10,
            )
            system = _build_system_prompt(anti)
            user = _build_user_prompt(spec, search_top_k)
            llm = LLMRouter(db=db, company_id=meta_tree.company_id)
            actor_model = context.get("actor_model") or context.get("model_name")
            critic_model = resolve_critic_model(
                entity_override=context.get("spec_critic_model_override"),
                actor_model=actor_model,
            )
            try:
                response = await llm.call_llm(
                    task_type="thinking",
                    system_prompt=system,
                    user_prompt=user,
                    temperature=0.2,
                    max_tokens=1200,
                    model_override=critic_model,
                )
                output = getattr(response, "output", "") or ""
                try:
                    from src.ai.usage_service import UsageService
                    svc = UsageService(db)
                    model = getattr(response, "model_name", "") or ""
                    if model:
                        if response.prompt_tokens:
                            await svc.log_usage(
                                company_id=meta_tree.company_id,
                                service_sku=f"{model}-in",
                                raw_quantity=float(response.prompt_tokens),
                                attribution="meta_spec_critic",
                            )
                        if response.completion_tokens:
                            await svc.log_usage(
                                company_id=meta_tree.company_id,
                                service_sku=f"{model}-out",
                                raw_quantity=float(response.completion_tokens),
                                attribution="meta_spec_critic",
                            )
                except Exception:                                            # pragma: no cover
                    pass
            except Exception as exc:                                        # noqa: BLE001
                logger.warning("spec_critic LLM call failed: %s", exc)
                output = ""

            parsed = parse_json_object(output, warn_label="meta_spec_critic") or {}
            normalised = _normalise_verdict(parsed)

            # Persist novel anti-patterns (severity ≥ med).
            for c in normalised["concerns"]:
                if _SEVERITY_RANK[c["severity"]] >= _SEVERITY_RANK["med"] and c["issue"]:
                    try:
                        await meta_tree.add_anti_pattern(
                            title=c["issue"],
                            suggestion=c["fix_suggestion"],
                            severity=c["severity"],
                            related_tags=list(spec.get("tags") or []),
                        )
                    except Exception:                                       # pragma: no cover
                        logger.debug("anti-pattern persist failed; continuing")
            await db.commit()
            normalised["model_used"] = critic_model or "(actor-same)"
            return json.dumps(normalised)


__all__ = ["MetaSpecCriticTool"]
