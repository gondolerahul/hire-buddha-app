# Track 8 — Tool & Cost Consolidation (Week 11)

> **Owner:** Platform / cost engineer.
> **Duration:** 5 working days.
> **Behaviour change:** Tool cost lookup, tool resilience (reformat-retry
>   + fallback chain), and tool registry layout consolidated. New cost
>   telemetry attribution. Behind `tools.cost_resolver_v2_enabled` and
>   `tools.resilience_v2_enabled`.
> **Risk:** Low-Medium. Cost paths affect billing; tool resilience
>   regressions are quickly visible.
> **Goal mapping:** G6 (clean layout), G8 (cost-aware budget), G3
>   indirect (CriticPipeline trust scores feed off provenance).

---

## 1. Objectives (functional)

After Track 8:

1. **One** `ToolCostResolver` service replaces the two duplicated
   60-line tool-cost lookup blocks in `step_executor.py`. Both code
   paths (direct TOOL_CALL and REACT AFC) call it.
2. **One** `ToolResilience` module owns reformat-retry + fallback
   chain. Used by both direct TOOL_CALL and REACT (no more silent
   asymmetry).
3. Cost telemetry gains structured **attribution**: every Decimal
   added to `run.total_cost_usd` tags itself as
   `planner | actor_step | critic_pre | critic_post | critic_align |
   critic_super | reformat_retry | meta_review | dreaming | tool |
   child_run`.
4. Tools are grouped by **subdomain** (`tools/core/`, `tools/documents/`,
   `tools/media/`, `tools/sandbox/`, `tools/email/`, `tools/crm/`,
   `tools/integrations/social/`, `tools/integrations/ads/`,
   `tools/meta/`, `tools/management/`).
5. Each registered tool is tagged `ACTIVE`, `EXPERIMENTAL`, or
   `DEPRECATED`. `EXPERIMENTAL` tools require an explicit per-company
   opt-in flag (`tools.experimental.{tool_id}`) before they show up to
   agents.
6. The cost dashboard from Track 9 shows cost-by-attribution per run /
   per entity / per company.

---

## 2. Scope

### In scope

* New: `governance/tool_cost_resolver.py`.
* New: `tools/resilience.py` (`ToolResilience.run(...)`).
* Refactor: `step_executor.py` — call the new services; delete the
  ~120 lines of duplicate cost lookup.
* New: `services/cost_attribution.py` (`CostLedger`).
* New: `usage_logs.attribution` column (Alembic migration).
* Tool registry audit: tag every tool in `tools/__init__.py` with
  `ToolStatus`. Move files into subdomain folders (mechanical).
* Feature flag plumbing for `tools.experimental.*` per company.
* Telemetry events for cost attribution.

### Out of scope

* Tool synthesis (P3).
* MCP / external tool integration.
* Renaming any tool's `name` (would break entities).
* Repricing — only attribution and consolidation. The actual
  `internal_cost` values in `IntegrationRegistry` are unchanged.

---

## 3. Architecture (technical)

### 3.1 `ToolCostResolver`

```python
# governance/tool_cost_resolver.py
class ToolCostResolver:
    """
    Single entry point for charging tool cost to a run.

    Lookup priority:
      1. IntegrationRegistry.service_sku == tool_id
      2. IntegrationRegistry.service_sku ∈ _TOOL_SKU_MAP[tool_id]
      3. _TOOL_FIXED_COST[tool_id]  (e.g. image_generation = $0.04)
      4. 0   (warning logged once per process)

    Returns the charged Decimal so the caller can pass it into the
    AgentLoop.Budget.consume() call.
    """

    def __init__(self, db, company_id):
        self.db = db
        self.company_id = company_id
        self._cache: dict[str, Decimal | None] = {}   # per-process cache

    async def charge(self, *,
                     run: ExecutionRun,
                     tool_id: str,
                     latency_ms: int = 0,
                     attribution: str = "tool",
                     ) -> Decimal:
        cost = await self._resolve(tool_id)
        if cost is None or cost == 0:
            return Decimal("0")
        ledger = CostLedger(self.db)
        await ledger.add(
            run_id=run.id, company_id=run.company_id,
            amount=cost, attribution=attribution,
            sku=tool_id, latency_ms=latency_ms,
        )
        run.total_cost_usd = (run.total_cost_usd or Decimal("0")) + cost
        return cost
```

`_TOOL_SKU_MAP` and `_TOOL_FIXED_COST` move from `step_executor.py`
into this file as module-level constants. There is now **one** source
of truth.

### 3.2 `ToolResilience`

```python
# tools/resilience.py
class ToolResilience:
    """
    Wraps tool execution with reformat-retry + fallback-chain.
    Used by both direct TOOL_CALL and REACT AFC paths.
    """

    def __init__(self, llm_router, cost_resolver, fallback_table):
        self.llm = llm_router
        self.cost = cost_resolver
        self.fallback = fallback_table   # from tool_fallback.py

    async def run(self, *,
                  run, entity, tool_id, raw_input, extra_context,
                  step_name: str = "",
                  step_description: str = "") -> ToolResult:
        result = await ToolExecutor.execute_tools(
            [{"tool": tool_id, "input": raw_input}],
            extra_context=extra_context,
        )
        tr = result[0]
        failure = classify_tool_failure(tr)
        if failure == FailureKind.NONE:
            return tr

        # Step 1: reformat-retry on FORMAT / EMPTY
        if failure in {FailureKind.FORMAT, FailureKind.EMPTY, FailureKind.IO}:
            new_input = await self._reformat(run, entity, tool_id,
                                              raw_input, tr, step_description)
            if new_input and new_input != raw_input:
                retry = (await ToolExecutor.execute_tools(
                    [{"tool": tool_id, "input": new_input}],
                    extra_context=extra_context))[0]
                if classify_tool_failure(retry) == FailureKind.NONE:
                    return retry

        # Step 2: fallback chain
        alt_id, alt_input = self.fallback.get_fallback_tool(tool_id, raw_input)
        if alt_id:
            alt_result = (await ToolExecutor.execute_tools(
                [{"tool": alt_id, "input": alt_input}],
                extra_context=extra_context))[0]
            if classify_tool_failure(alt_result) == FailureKind.NONE:
                alt_result.tool = f"{tool_id}→{alt_id}"
                return alt_result

        # Step 3: final empty marker
        tr.output = (f"[TOOL_EMPTY] Tool '{tool_id}' returned no usable "
                     f"output after retries. Failure kind: {failure.value}")
        tr.success = False
        return tr
```

`FailureKind` is an enum derived from the keyword sets in
`step_executor._execute_tool_call:388-420`.

### 3.3 `CostLedger`

```python
# services/cost_attribution.py
class CostLedger:
    """
    Writes a row to usage_logs for each cost addition, tagging it with
    a structured attribution key.

    All cost additions in the new code paths MUST go through here.
    """

    VALID_ATTRIBUTIONS = {
        "planner", "actor_step", "critic_pre", "critic_post",
        "critic_align", "critic_super", "reformat_retry",
        "meta_review", "dreaming", "tool", "child_run",
        "embedding", "meta_spec_critic", "test_driver",
    }

    async def add(self, *, run_id, company_id, amount: Decimal,
                  attribution: str, sku: str | None = None,
                  latency_ms: int = 0, log_metadata: dict | None = None):
        if attribution not in self.VALID_ATTRIBUTIONS:
            logger.warning(f"Unknown attribution {attribution!r}; recording as 'tool'")
            attribution = "tool"
        ...
        # INSERT into usage_logs(..., attribution=attribution)
```

### 3.4 `usage_logs.attribution` column

Add a `Mapped[str]` column with index. Allows queries:

```sql
SELECT attribution, SUM(calculated_cost)
FROM usage_logs
WHERE company_id = $1 AND created_at > now() - interval '7 days'
GROUP BY attribution
ORDER BY 2 DESC;
```

This drives the Track 9 cost dashboard.

### 3.5 Tool subdomain layout

```
backend/src/ai/tools/
├── __init__.py              ← registrations + ACTIVE / EXPERIMENTAL tags
├── base.py
├── resilience.py            ← NEW (this Track)
├── core/
│   ├── calculator.py
│   ├── search.py
│   ├── batch_search.py
│   ├── scraper.py
│   ├── browser_tool.py
│   ├── text_extractor.py    ← was at ai/text_extractor.py
│   └── file_writer.py
├── documents/
│   ├── pdf_generator.py
│   ├── docx_tool.py
│   ├── pptx_tool.py
│   ├── excel.py
│   ├── xlsx_engine.py
│   └── document_save.py
├── media/
│   ├── image_generation.py
│   └── video_generation.py
├── sandbox/
│   ├── sandbox_executor.py
│   ├── sandbox_provision.py
│   └── terminal_tool.py
├── email/
│   └── email_tool.py
├── crm/
│   └── crm_tools.py
├── integrations/
│   ├── social/ (15 files unchanged)
│   └── ads/    (separate ads files moved out of social/)
├── meta/        (unchanged)
└── management/
    ├── router.py
    └── service.py
```

This is a `git mv` exercise + updated `tools/__init__.py` imports. The
registered tool *names* don't change.

### 3.6 Tool status tagging

```python
# tools/base.py — add:
class ToolStatus(str, Enum):
    ACTIVE       = "ACTIVE"
    EXPERIMENTAL = "EXPERIMENTAL"
    DEPRECATED   = "DEPRECATED"


class Tool:
    name: str
    description: str
    status: ToolStatus = ToolStatus.ACTIVE     # ← new class attr
```

`ToolRegistry.get_tools_for_company(company_id)` already exists; extend
to filter `EXPERIMENTAL` tools out unless
`tools.experimental.{tool_id}` is enabled for the company.

---

## 4. Detailed deliverables

### 4.1 T8-1 — `services/cost_attribution.py` + migration (Day 1 AM)

* Alembic migration `p11t08_usage_logs_attribution`:

  ```python
  def upgrade():
      op.add_column("usage_logs",
                    sa.Column("attribution", sa.String(40),
                              nullable=False, server_default="tool"))
      op.create_index("ix_usage_logs_attribution",
                      "usage_logs", ["attribution"])
  ```

  Backfill is the server default; no UPDATE needed.

* `services/cost_attribution.py` per §3.3.

### 4.2 T8-2 — `governance/tool_cost_resolver.py` (Day 1 PM)

Per §3.1. Move `_TOOL_SKU_MAP` and `_TOOL_FIXED_COST` constants out of
`step_executor.py`.

### 4.3 T8-3 — `tools/resilience.py` (Day 2)

Per §3.2. Classify failure kinds:

```python
class FailureKind(str, Enum):
    NONE    = "NONE"
    FORMAT  = "FORMAT"
    IO      = "IO"
    EMPTY   = "EMPTY"
    TIMEOUT = "TIMEOUT"
    OTHER   = "OTHER"


def classify_tool_failure(tr: ToolResult) -> FailureKind:
    """Extracted verbatim from step_executor's keyword logic."""
    ...
```

### 4.4 T8-4 — Refactor `step_executor.py` to use both (Day 3)

Direct TOOL_CALL path:

```python
# step_executor._execute_tool_call (refactored)
resilient = ToolResilience(llm_router=..., cost_resolver=...,
                           fallback_table=...)
tr = await resilient.run(
    run=run, entity=entity, tool_id=tool_id,
    raw_input=raw_input, extra_context=extra_context,
    step_name=step.name, step_description=step.description,
)
await self.cost_resolver.charge(
    run=run, tool_id=tool_id,
    latency_ms=int((datetime.utcnow() - start_time).total_seconds()*1000),
    attribution="tool",
)
```

REACT AFC path (`_execute_tools` closure inside `_execute_thought`):
same wrapper — calls `resilient.run(...)` instead of direct
`ToolExecutor.execute_tools`.

The ~120-line block of duplicate cost lookup is deleted.

`_reformat_tool_input` moves into `tools/resilience.py::ToolResilience._reformat`
and is no longer reachable from `step_executor`.

### 4.5 T8-5 — Tool subdomain `git mv` + `tools/__init__.py` rewrite (Day 4 AM)

Mechanical. Update `tools/__init__.py` to:

```python
# tools/__init__.py
from src.ai.tools.base import Tool, ToolRegistry, ToolStatus
# Core
from src.ai.tools.core.calculator import CalculatorTool
from src.ai.tools.core.search import WebSearchTool
from src.ai.tools.core.batch_search import BatchWebSearchTool
from src.ai.tools.core.scraper import ScraperTool
from src.ai.tools.core.browser_tool import HeadlessBrowserTool
from src.ai.tools.core.text_extractor import TextExtractorTool
from src.ai.tools.core.file_writer import FileWriterTool
# Documents
from src.ai.tools.documents.pdf_generator import PDFGeneratorTool
from src.ai.tools.documents.docx_tool import DocxTool
from src.ai.tools.documents.pptx_tool import PptxTool
from src.ai.tools.documents.excel import ExcelTool
from src.ai.tools.documents.document_save import DocumentSaveTool
# Media
from src.ai.tools.media.image_generation import ImageGenerationTool
from src.ai.tools.media.video_generation import VideoGenerationTool
# Sandbox
from src.ai.tools.sandbox.sandbox_executor import SandboxCodeTool
from src.ai.tools.sandbox.terminal_tool import TerminalTool
# Email
from src.ai.tools.email.email_tool import (
    EmailIngestTool, EmailClassifyTool, EmailDraftTool, EmailSendTool,
)
# CRM
from src.ai.tools.crm.crm_tools import (
    GetCurrentDateTimeTool, WhatsAppSendTenantTool,
    GoogleCalendarCreateEventTool, CRMUpdateLeadTool,
)
# Integrations: social / ads (15+ tools) — auto-import via glob
from src.ai.tools.integrations.social import *      # noqa: F401, F403
from src.ai.tools.integrations.ads import *         # noqa: F401, F403
# Meta — unchanged location
from src.ai.tools.meta import *                     # noqa: F401, F403

ToolRegistry.register(CalculatorTool())
...
```

### 4.6 T8-6 — Tool status tagging (Day 4 PM)

Tag each tool in its class:

```python
class HeadlessBrowserTool(Tool):
    name = "headless_browser"
    status = ToolStatus.ACTIVE
    ...

class VideoGenerationTool(Tool):
    name = "video_generation"
    status = ToolStatus.EXPERIMENTAL   # high cost; opt-in only
    ...
```

Initial tagging table (proposed; adjust per Track 8 audit):

| Tool | Status |
|------|--------|
| calculator, web_search, batch_web_search, scraper_tool, headless_browser, pdf_generator, docx_tool, pptx_tool, excel, file_writer, document_save, image_generation, email_*, crm_*, get_current_datetime, whatsapp_send_tenant, google_calendar_create_event, sandbox_code, terminal_tool | ACTIVE |
| video_generation | EXPERIMENTAL (high cost; opt-in per company) |
| All `tools/integrations/social/*` | EXPERIMENTAL (per-company OAuth gated) |
| All `tools/integrations/ads/*` | EXPERIMENTAL |
| Any tool not referenced in `SeedEntities/` or by Meta-Agent fixtures | DEPRECATED (audit) |

`ToolRegistry.get_tools_for_company(company_id)` filters out
`EXPERIMENTAL` unless the company has `tools.experimental.{tool_id} =
true`.

### 4.7 T8-7 — Wire attribution into every cost path (Day 5 AM)

Every LLM and tool cost addition migrates to `CostLedger.add(...)` with
the correct attribution:

| Site | attribution |
|------|-------------|
| `planning/planner_service._log_planner_usage` | `"planner"` |
| `core/reasoning/react._execute_tools` (after a tool call) | `"tool"` |
| `step_executor._execute_thought` final LLM call | `"actor_step"` |
| `planning/critic_pipeline._pre_critic` | `"critic_pre"` |
| `planning/critic_pipeline._post_critic` | `"critic_post"` |
| `planning/critic_pipeline._alignment_critic` | `"critic_align"` |
| `planning/supervisor_critic.assess` | `"critic_super"` |
| `tools/resilience._reformat` | `"reformat_retry"` |
| `memory/dreaming/engine.dream` (LLM calls) | `"dreaming"` |
| `tools/meta/spec_critic` | `"meta_spec_critic"` |
| `meta/board/test_driver` | `"test_driver"` |
| `memory/embedding_service` | `"embedding"` |
| `step_executor._execute_child_invocation` rollup | `"child_run"` (the parent's row) |

### 4.8 T8-8 — Tests + dashboard wiring (Day 5 PM)

Per §9. Track 9 dashboards consume `usage_logs.attribution`.

---

## 5. Database / schema changes

### 5.1 `p11t08_usage_logs_attribution`

Add `attribution VARCHAR(40) NOT NULL DEFAULT 'tool'` with index. See
§4.1.

### 5.2 `ToolStatus` is enum-in-code only

No SQL change for tool status; it's a Python attribute.

### 5.3 Feature flags table — companion entries

Per-company experimental tool flags use the existing `feature_flags`
table from Track 2 (`flag_key = "tools.experimental.video_generation"`).

---

## 6. API changes

### 6.1 `GET /api/v1/tools` returns `status`

Existing endpoint adds a field:

```jsonc
{"tool_id":"web_search","description":"…","status":"ACTIVE", ...}
```

UI for entity tool selection greys out non-ACTIVE without explicit
company override.

### 6.2 New admin endpoint

```
POST /api/v1/admin/tools/{tool_id}/experimental
  body: {"enabled": true|false}
```

Toggles the per-company flag.

### 6.3 New cost dashboard endpoints

```
GET /api/v1/runs/{run_id}/cost_attribution
GET /api/v1/companies/{company_id}/cost_attribution?since=7d
```

Returns `{attribution: amount}` aggregates.

---

## 7. Telemetry events

| Event | Payload | When |
|-------|---------|------|
| `agent.cost.charged` | `{run_id, attribution, sku, amount_usd, latency_ms}` | every charge |
| `agent.tool.resilience.reformat_attempt` | `{run_id, tool_id, failure_kind}` | every reformat |
| `agent.tool.resilience.fallback_taken` | `{run_id, from_tool, to_tool, success}` | every fallback |
| `agent.tool.resilience.final_empty` | `{run_id, tool_id, failure_kind}` | rare |
| `agent.tool.status_filtered` | `{tool_id, company_id, reason}` | rare |

---

## 8. Feature flags

| Flag | Default | Notes |
|------|---------|-------|
| `tools.cost_resolver_v2_enabled` | ON | Master |
| `tools.resilience_v2_enabled` | ON | Master |
| `tools.experimental.{tool_id}` | OFF per company | Opt-in |
| `tools.cost_attribution_required` | ON | Future: enforce attribution at insert time (Phase 12) |

---

## 9. Tests

### 9.1 Unit

* `test_tool_cost_resolver_priority` — SKU > map > fixed > 0.
* `test_tool_cost_resolver_cache_one_lookup_per_process` — second call
  same process doesn't re-query DB.
* `test_resilience_reformat_recovers` — fixture tool emits malformed
  JSON; reformat yields valid → success.
* `test_resilience_fallback_taken` — primary tool empty; fallback table
  has alt → alt used.
* `test_resilience_final_empty_marker` — both fail → output starts
  with `[TOOL_EMPTY]`.
* `test_cost_ledger_unknown_attribution_warns` — bad attribution falls
  through to `"tool"` with warning event.
* `test_tool_registry_filters_experimental` — EXPERIMENTAL tool hidden
  when no opt-in; surfaced when flag on.

### 9.2 Integration

* `test_react_path_uses_resilience` — failing REACT tool call now
  triggers reformat (previously silent).
* `test_no_duplicate_cost_lookup_block` — `grep -RIn "_TOOL_SKU_MAP"
  backend/src/ai/step_executor.py` is empty.
* `test_attribution_appears_in_usage_logs` — run completes; rows in
  `usage_logs` cover all expected attributions.

### 9.3 Smoke / parity

* Full regression. Acceptance: cost ±5% of Track 7 baseline; tool
  reliability (success rate per tool) ≥ Track 7 baseline.

---

## 10. Acceptance criteria

1. `governance/tool_cost_resolver.py` is the only place reading
   `_TOOL_SKU_MAP`. The constants no longer appear in
   `step_executor.py`.
2. `tools/resilience.py` is called from both direct TOOL_CALL and
   REACT AFC paths.
3. `usage_logs.attribution` column exists; new rows are populated;
   queries by attribution work.
4. Tools live under subdomain folders; `tools/__init__.py` imports
   from the new paths; tool *names* are unchanged.
5. `EXPERIMENTAL` tools require opt-in.
6. `mypy --strict` clean on new files.

---

## 11. Effort breakdown (5 working days)

| Day | Work |
|-----|------|
| 1 AM | T8-1: migration + CostLedger |
| 1 PM | T8-2: ToolCostResolver |
| 2 | T8-3: ToolResilience + FailureKind classifier |
| 3 | T8-4: refactor step_executor |
| 4 AM | T8-5: subdomain `git mv` + tools/__init__.py |
| 4 PM | T8-6: tool status tagging + opt-in flag wiring |
| 5 AM | T8-7: attribution wired into every cost path |
| 5 PM | T8-8: tests + endpoints + PR |

---

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Subdomain `git mv` breaks imports somewhere obscure | M | Worker boot fails | Single `tools/__init__.py` is the only import surface; run boot smoke + parity tests |
| Attribution misclassified (silent default to "tool") | M | Dashboard wrong | CI lint: every `CostLedger.add` call site sets `attribution` explicitly (grep check) |
| EXPERIMENTAL tag removes a tool used by an existing entity | H | Production entity fails | Migration script audits existing entities; any in-use EXPERIMENTAL tool gets the per-company flag flipped ON automatically |
| Resilience adds latency for slow networks | L | Worse UX on cold cache | Cache schema lookups; cap retries to 1 per failure kind |
| ToolCostResolver cache stale after IntegrationRegistry update | L | Wrong cost briefly | Cache TTL 5 minutes; admin endpoint to flush |
| Reformat-retry now spends more LLM cost on the REACT path | M | Cost rises 5-10% on noisy tools | Attribution shows it; calibration job can disable reformat for specific tools |

---

## 13. Dependencies

* **Upstream:**
  * Track 2 (FeatureFlags service).
  * Track 6 (Provenance — sets the trust score that the Critic uses).
* **Downstream:**
  * Track 9 (dashboard reads `usage_logs.attribution`).

---

## 14. Open questions

* Should `child_run` attribution roll up further to "what kind of child"
  (research / synthesize / etc.)? Defer to Phase 12 once
  `task_class` data matures.
* Should EXPERIMENTAL tools be enabled-by-default in DEV environments?
  Yes — environment variable `DEFAULT_EXPERIMENTAL_TOOLS = "true"` in
  dev.
