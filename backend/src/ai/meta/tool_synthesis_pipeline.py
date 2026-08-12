"""ai.meta.tool_synthesis_pipeline — the end-to-end tool-synthesis orchestrator.

Ties the four `06` §2 stages into one auditable pipeline:

    ToolSpec ─▶ ToolSmith (LLM writes source)
             ─▶ ToolValidator (AST static gate)
             ─▶ ToolSandboxTester (replay examples in the container, `02`)
             ─▶ ToolRedTeam (adversarial LLM review)
             ─▶ register DRAFT (ToolRegistryEntry, status=DRAFT, trust=low)

Every stage can short-circuit; a structured :class:`SynthesisReport` records
each verdict so the result is a complete audit trail (`06` §2.2 control 4). The
collaborators are injected so the whole pipeline is unit-testable without live
LLM/Docker. Registration is gated: it only happens when *all* gates pass.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Optional
from uuid import UUID

from src.ai.meta.tool_red_team import ToolRedTeam
from src.ai.meta.tool_sandbox_tester import ToolSandboxTester
from src.ai.meta.tool_validator import ToolValidator
from src.ai.schemas.tools import ToolSpec

logger = logging.getLogger(__name__)

__all__ = ["SynthesisReport", "ToolSynthesisPipeline", "register_draft_tool"]


@dataclass
class SynthesisReport:
    spec_name: str
    stage: str = "start"          # the stage reached
    ok: bool = False
    source: str = ""
    validator: dict[str, Any] = field(default_factory=dict)
    sandbox: dict[str, Any] = field(default_factory=dict)
    red_team: dict[str, Any] = field(default_factory=dict)
    registered_tool_id: Optional[str] = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def register_draft_tool(
    db: Any,
    company_id: UUID,
    spec: ToolSpec,
    source: str,
    *,
    audit: dict[str, Any],
    created_by: Optional[UUID] = None,
) -> str:
    """Persist a DRAFT ToolRegistryEntry + register a sandbox-only runtime tool.

    Returns the new entry id. The DB row is the durable provenance record;
    ``configuration`` carries status/trust/spec/source/audit so no schema change
    is needed. The runtime tool is registered tenant-scoped with status=DRAFT so
    the visibility gate keeps it opt-in and never global.
    """
    import uuid as _uuid

    from src.ai.orm.tools import ToolRegistryEntry
    from src.ai.tools import ToolRegistry
    from src.ai.tools.sandbox.synthesized_tool import SandboxedSynthesizedTool

    entry_id = _uuid.uuid4()
    entry = ToolRegistryEntry(
        id=entry_id,
        company_id=company_id,
        name=spec.name,
        display_name=spec.name,
        description=spec.description,
        category="synthesized",
        tool_type="SYNTHESIZED",
        function_schema={"name": spec.name, "parameters": spec.input_schema},
        is_enabled=False,
        configuration={
            "status": "DRAFT",
            "trust": "low",
            "network_policy": spec.network_policy.value,
            "source": source,
            "spec": spec.model_dump(mode="json"),
            "audit": audit,
        },
        created_by=created_by,
    )
    db.add(entry)
    await db.commit()

    ToolRegistry.register_tenant_tool(company_id, SandboxedSynthesizedTool(spec, source))
    return str(entry_id)


class ToolSynthesisPipeline:
    """Runs the synthesis stages end to end. Collaborators are injectable."""

    def __init__(
        self,
        *,
        smith: Any = None,
        validator: Optional[ToolValidator] = None,
        tester: Optional[ToolSandboxTester] = None,
        red_team: Optional[ToolRedTeam] = None,
    ) -> None:
        # ToolSmith imported lazily to keep this module import-light.
        if smith is None:
            from src.ai.meta.board.tool_smith import ToolSmith
            smith = ToolSmith()
        self.smith = smith
        self.validator = validator or ToolValidator()
        self.tester = tester or ToolSandboxTester()
        self.red_team = red_team or ToolRedTeam()

    async def run(
        self,
        spec: ToolSpec,
        *,
        llm: Any,
        context: Optional[dict[str, Any]] = None,
        db: Any = None,
        company_id: Optional[UUID] = None,
        created_by: Optional[UUID] = None,
        model_override: Optional[str] = None,
    ) -> SynthesisReport:
        report = SynthesisReport(spec_name=spec.name)

        # 1. Synthesize.
        try:
            synth = await self.smith.synthesize(spec, llm=llm, model_override=model_override)
        except Exception as exc:  # noqa: BLE001
            report.stage = "synthesize"
            report.error = f"ToolSmith failed: {type(exc).__name__}: {exc}"
            return report
        report.source = synth.source
        if not synth.source.strip():
            report.stage = "synthesize"
            report.error = "ToolSmith produced no source"
            return report

        # 2. Static validation.
        vres = self.validator.validate(synth.source, spec)
        report.validator = {"ok": vres.ok, "summary": vres.summary(),
                            "imports": sorted(vres.imported_modules)}
        if not vres.ok:
            report.stage = "validate"
            return report

        # 3. Sandbox replay.
        sbox = await self.tester.run_examples(synth.source, spec, context or {})
        report.sandbox = {"ok": sbox.ok, "summary": sbox.summary(),
                          "outcomes": [asdict(o) for o in sbox.outcomes]}
        if not sbox.ok:
            report.stage = "sandbox"
            return report

        # 4. Red-team.
        rt = await self.red_team.review(spec, synth.source, llm=llm)
        report.red_team = {"verdict": rt.verdict,
                           "concerns": [asdict(c) for c in rt.concerns],
                           "model_used": rt.model_used}
        if not rt.passed:
            report.stage = "red_team"
            return report

        # 5. Register DRAFT (only if a DB session + company were supplied).
        report.stage = "register"
        if db is not None and company_id is not None:
            audit = {
                "smith_model": synth.model_used,
                "validator": report.validator,
                "sandbox": report.sandbox["summary"],
                "red_team_model": rt.model_used,
            }
            report.registered_tool_id = await register_draft_tool(
                db, company_id, spec, synth.source, audit=audit, created_by=created_by,
            )
        report.ok = True
        return report
