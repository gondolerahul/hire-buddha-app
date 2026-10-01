# PO-06 — Tool Stack Audit

> **What this document is:** the deliverable for **PO-06** ("audit the entire tools
> stack and list what needs to be fixed"). It re-verifies the two existing tool-layer
> registers against the code as it stands today, records the findings that were **not**
> already captured, and ends with a single prioritised "what needs fixing" list.
> **Product owner, 2026-09-29:** *audit the entire tools stack and list what needs to be
> fixed. The deliverable is the audit, not a code change.*
> **Compiled:** 2026-09-29, on branch `roadmap-development-defect-fixes`.
> **Scope:** `backend/src/ai/tools/**`, `tool_executor.py`, the tool paths in
> `step_executor.py`, `tool_management_*`, `social_*`, `tool_fallback.py`, the sandbox
> runtime, and the LLM REACT loop where it dispatches tools.

> **2026-10-01 — consolidated.** This register is now worked through
> [`CONSOLIDATED-KERNEL-TOOLS-PLAN.md`](CONSOLIDATED-KERNEL-TOOLS-PLAN.md), which merges
> registers 05, 06, 07, 09, 10, 11, TOOL-LAYER and PO-06 into one deduplicated list,
> adds the six-level hierarchy (R1) and the skill-first tool stack (R2), and orders the
> fixes in phases. Use the canonical id from its merge map in commits; status lines here
> are still updated as fixes land.

---

## How this relates to the existing registers

The tool layer already has the deepest coverage in the set. Two registers stand:

- [`TOOL-LAYER-DEFECTS.md`](TOOL-LAYER-DEFECTS.md) — **49 verified defects** (TL-01…TL-49),
  compiled 2026-08-27.
- [`09-TOOLS-DEFECTS.md`](09-TOOLS-DEFECTS.md) — **6 additions** (TX-01…TX-06) and 10
  improvements at doc-09 scope, compiled 2026-09-01.

This audit does **not** restate those 55 entries. It does three things:

1. **§2** re-verifies them against the current code and flags what has moved.
2. **§3** records **18 new defects** (TL-50…TL-67) the two passes did not capture.
3. **§4** is the prioritised fix list the product owner asked for.

New defects keep the `TL-nn` series so they live in one namespace; the full entries are
here, and [`TOOL-LAYER-DEFECTS.md`](TOOL-LAYER-DEFECTS.md) reserves the range with a
pointer back to this file.

---

## 1. Inventory — what is actually registered

`tools/__init__.py` makes **97** `ToolRegistry.register(...)` calls (was 98; the
`video_generation` shim was deleted 2026-09-29 as PO-17). Live count by status:

| Status | Count | What |
|---|---:|---|
| `ACTIVE` | **29** | Every non-social tool except the four below |
| `EXPERIMENTAL` | **68** | The **64** social tools + `video_generate`, `video_edit`, `video_add_sound`, `tool_synthesis` |
| `DEPRECATED` | 0 | — |

So the three "how many tools" answers are now: **97** registered, **29** `ACTIVE`,
**64** social. The number a customer can actually rely on is **29** — and even that is
optimistic (see TL-66: three of the 29 do not import on a clean install). The register's
earlier "≈34 usable" figure predates the `video_generation` deletion and counted by
usefulness rather than status; the status count is 29.

**The 33 non-social tools** (all `ACTIVE` except the 3 video tools + `tool_synthesis`):
`calculator`, `web_search`, `batch_web_search`, `scraper_tool`, `excel_tool`,
`pdf_generator`, `file_writer`, `docx_tool`, `pptx_tool`, `document_save`,
`email_ingest`, `email_classify`, `email_draft`, `email_send`, `image_generation`,
`video_generate`, `video_edit`, `video_add_sound`, `sandbox_code`, `terminal`,
`headless_browser`, `get_current_datetime`, `whatsapp_send_tenant`,
`google_calendar_create_event`, `crm_update_lead`, `meta_platform_introspect`,
`meta_registry_search`, `meta_schema_validator`, `meta_entity_creator`,
`meta_entity_executor`, `agent_introspect`, `agent_reflect`, `tool_synthesis`.

`meta_spec_critic` is instantiated but **not** registered (TX-04, still true).

**The 16 social platforms** (4 tools each): `linkedin`, `twitter`, `facebook`,
`instagram`, `google_ads`, `youtube`, `tiktok`, `reddit`, `quora`, `pinterest`,
`meta_ads`, `linkedin_ads`, `linkedin_sales_nav`, `youtube_ads`, `x_ads`,
`snapchat_ads`. Three lists disagree about which of these exist (this is PO-07):

| List | Count | Members |
|---|---:|---|
| Tool modules | 16 | all of the above |
| `VALID_PLATFORMS` (connectable via the API) | 9 | linkedin, twitter, facebook, instagram, google_ads, youtube, tiktok, reddit, quora |
| `PLATFORM_REFRESH_CONFIG` (can refresh a token) | 8 | the 9 above **minus quora** |

So seven platforms have tools an agent can be given but no way to store a credential
(TL-40 / PO-07), and `quora` can be connected but its token can never refresh. There is
**no frontend** for social connections at all — the only way to create one is a raw
`POST /api/social-connections` (see §3, and PO-07).

---

## 2. Re-verification of the existing registers

Every TL-01…TL-49 and TX-01…TX-06 entry was re-read against the current code. **All still
hold** except the three notes below. Only one tool-layer commit has landed since the deep
pass (2026-08-27): `a8fb38e` (PO-17, `video_generation` deleted).

| Entry | Status now | Note |
|---|---|---|
| **TL-29** — "`_sandbox_base_dir` defined twice in `runtime.py`; the second shadows the first" | **Stale as written** | `runtime.py` defines it **once** ([runtime.py:426](../../../backend/src/ai/tools/sandbox/runtime.py:426)). There are still **two** copies across the package — the other is in [`tenant_manager.py:59`](../../../backend/src/ai/tools/sandbox/tenant_manager.py:59) — so the duplication the entry is really about is real, but it is cross-module, not a within-file shadow. Fix the entry's wording, keep the dedup intent. |
| **TX-01** — "the per-company sandbox flag is never read" | **Mechanism now exists; outcome unchanged** | `resolve_sandbox_runtime` ([runtime.py:367](../../../backend/src/ai/tools/sandbox/runtime.py:367)) now resolves `sandbox.container_runtime_enabled` from the DB and threads it into the context as `container_runtime`, and the exec/browser tools call it. **But** it only honours an *explicit* DB row (entity/company/global); the dev DB has **zero** `feature_flags` rows, so it falls through to `settings.SANDBOX_CONTAINER_RUNTIME_ENABLED` (`False`). The `DEFAULTS["sandbox.container_runtime_enabled"] = True` is still never consulted by the sandbox path. Net effect is exactly what TX-01 describes — flag says on, sandbox runs off — so **TX-01 stands**, but the "never threaded" clause is now out of date. |
| **Counts** in TL-13, PO-06, TX-I3 | **Shifted by one** | "98 tools / 69 unverified" → **97 / 68** after PO-17. "≈34 usable" → **29 `ACTIVE`**. |

Everything else — the four root faults, the T0 tenant-boundary holes (TL-01…TL-09), the
declared-but-unenforced controls (TL-10…TL-22), the T2 deletions, the T3 correctness
items, and the T4 false-success integrations (TL-43…TL-49) — was confirmed against the
code and **remains accurate**. The social re-checks specifically confirmed: `quora`
still targets the fabricated `api.quora.com/v1` (TL-23); `x_ads` still sends OAuth2
bearer + JSON where the X Ads API needs OAuth 1.0a + form encoding (TL-24); `youtube_ads`
still pins Google Ads **v17** while `google_ads` uses **v18** and reads `customer_id`
from the model (TL-25, TL-09); LinkedIn still pins `202401` in 12 places (TL-48);
`youtube_upload_video` still never sends the media (TL-43); `google_ads_create_campaign`
is still two non-transactional mutates (TL-49).

---

## 3. New defects (TL-50 … TL-67)

Not captured by either existing pass. Each was confirmed by reading the cited code;
several were also observed in the dev database (§4).

### TL-50 — The model can call any registered tool, not just the entity's

**✅ Verified · Critical**

The REACT loop advertises only the entity's tools, but **execution is not restricted to
them**. `ToolExecutor.execute_from_function_calls` resolves whatever name the model
returns straight out of the global registry with no check that the entity was granted it
([tool_executor.py:119](../../../backend/src/ai/tool_executor.py:119)); the Gemini adapter
forwards every `function_call` the model emits
([gemini_adapter.py:364](../../../backend/src/ai/llm/gemini_adapter.py:364)) and nothing
in between filters by `entity.capabilities.tools`. The voice path is the same
([websocket_handler.py:1070](../../../backend/src/voice/websocket_handler.py:1070)).

So an entity granted only `web_search` can call `email_send`, `sandbox_code`,
`crm_update_lead` or `whatsapp_send_tenant` if it can be prompted to name them — and the
"tool not found" error even lists all 97 names to teach it the vocabulary
([tool_executor.py:200](../../../backend/src/ai/tool_executor.py:200)). The only
allow-list check in the whole path is on the *fallback* substitute
(`ToolResilience._fallback_allowed`), not on the tool the model actually asked for.

**Fix:** resolve tools against `entity.capabilities.tools` (plus the auto-injected meta
set) at execution, not just at advertisement. Pair with TL-10 — thread `company_id` into
`get_tool` — so tenant tools and the grant list are enforced in one place.

### TL-51 — The resilience classifier fails a succeeding tool on its content

**✅ Verified · High**

`tools.resilience_v2_enabled` defaults **True**, so every REACT tool call runs through
`classify_tool_failure` ([resilience.py:62](../../../backend/src/ai/tools/resilience.py:62)).
It buckets by **substring of the output**, and the `EMPTY` / `TIMEOUT` / `IO` buckets do
**not** require `success == False`. A successful result whose text happens to contain
`"no results"`, `"timed out"`, `"deadline exceeded"` or `"no such file or directory"` —
ordinary content in a scraped page, a search summary, or an email body — is classified as
a failure. The wrapper then:

1. re-runs the tool with LLM-reformatted input (a second charge, and for a **write** tool
   — `email_send`, `crm_update_lead`, a social post — a second side effect), then
2. if the re-run also "fails", **replaces the real output** with
   `"[TOOL_EMPTY] … Failure kind: …"` and sets `success=False`.

So a tool that worked can be reported to the agent as empty, and a read that mentioned a
timeout triggers a duplicate write. Confirmed live: `research_gatherer` and
`google:python_interpreter` outputs were overwritten with `[TOOL_EMPTY] … ERROR_MSG` (§4).

**Fix:** gate `TIMEOUT`/`IO`/`EMPTY` on `success == False`, or classify on a structured
tool result rather than a substring. Never re-invoke a write tool on a reformat retry.

### TL-52 — A tool that returns an error is recorded and billed as a success

**✅ Verified · High**

Tools signal failure by returning `{"error": "..."}` or an `"Error: ..."` string, not by
raising. The executor only sets `success=False` when the call **raises**
([tool_executor.py:177](../../../backend/src/ai/tool_executor.py:177)), so every
error-string result is logged with `success=True`. That flag feeds:

- `ToolInteractionLog.success`, which the **tool-efficacy report** aggregates as the
  success rate ([reports_service.py:190](../../../backend/src/ai/reports_service.py:190)); and
- the cost path, which charges the call regardless (TL-19 / and see below).

Confirmed live: three `pdf_generator` calls that returned
`{"error": "PDF generation failed: … weasyprint …"}` are all logged `success=True` (§4).
The efficacy dashboard therefore shows those tools at 100 %.

**Fix:** parse the tool's own result envelope for an error marker and set `success`
accordingly; do not bill a failed call. Ultimately subsumed by the typed contract (TL-41).

### TL-53 — Run input is trusted as tool execution context

**✅ Verified · High**

`ExecutionRunCreate.input_data` is an unconstrained `Dict[str, Any]`
([schemas/execution.py:28](../../../backend/src/ai/schemas/execution.py:28)) stored
verbatim. The loop seeds every input key into `context_state`
([agent_loop.py:742](../../../backend/src/ai/core/agent_loop.py:742), skipping only
`feature_flags`, `cortex_tree_id`, `subtree_root_id`), and the step executor spreads the
whole context into the tool `extra_context`
([step_executor.py:861](../../../backend/src/ai/step_executor.py:861)). So keys the caller
put in `input_data` arrive as *trusted* context that the runtime treats as its own:

- `container_runtime: false` → forces `SubprocessRuntime`, i.e. runs sandbox code on the
  host even where the container runtime is enabled ([runtime.py:293](../../../backend/src/ai/tools/sandbox/runtime.py:293)).
- `__is_meta_agent__: true` → satisfies the meta gate in `entity_creator` and
  `tool_synthesis` (TL-65), bypassing runtime-creation governance.
- `persistent_browser: true` + `persona: "<other>"` → selects a browser profile dir by
  unsanitised `persona` under the company root ([runtime.py:421](../../../backend/src/ai/tools/sandbox/runtime.py:421)).
- `feature_flags: {...}` is honoured by the flag resolver's entity-extras source
  ([feature_flags.py:528](../../../backend/src/ai/core/feature_flags.py:528)) — the loop
  drops the top-level key, but any code reading flags from the materialised context still
  sees caller-supplied values.

**Fix:** build tool context from a server-minted allow-list of fields; never merge raw
run input into it. Reserve `__`-prefixed and control keys to the platform.

### TL-54 — The document tools read and write arbitrary host paths from the model

**✅ Verified · High**

`docx_tool`, `pptx_tool` and `excel_tool` take `file_path` from the model for `read`/
`update` with no confinement, and write to a model-supplied `save_as` (or overwrite
`file_path`) — anywhere the backend user can read or write
([docx_tool.py:159](../../../backend/src/ai/tools/documents/docx_tool.py:159),
[docx_tool.py:271](../../../backend/src/ai/tools/documents/docx_tool.py:271);
same shape in `pptx_tool` and `excel.py`). `create`'s `filename` is not `basename`d, so
`../` escapes the tenant dir. `document_save` copies any readable host path into the
tenant's artifact store and returns a download URL
([document_save.py:62](../../../backend/src/ai/tools/documents/document_save.py:62)) — a
read-anything-then-download primitive (`/etc/passwd`, another tenant's artifact, the
backend `.env`). `image_generation.reference_image_path` and
`video_generate.start_frame_path`/`end_frame_path` likewise read any host file and send it
to Google.

Under the host `SubprocessRuntime` (the default — TL-01) these are host-level file
access. `file_writer` is the one tool that confines itself (`os.path.basename` +
extension allow-list). TL-17 flagged this for the video `output_path` only; the document,
image and save tools have the same class of bug and are not covered.

**Fix:** resolve every model-supplied path against the tenant workspace root and reject
anything that escapes it; `basename` all output filenames; take sources as artifact
references (TL-09), never host paths.

### TL-55 — `pdf_generator` renders model HTML with a live fetcher

**✅ Verified · High**

`pdf_generator` converts model-supplied markdown to HTML and hands it to WeasyPrint with
the default URL fetcher ([pdf_generator.py:460](../../../backend/src/ai/tools/documents/pdf_generator.py:460)).
Markdown passes raw HTML through, so `<img src="file:///etc/passwd">`,
`<link>`/`<object>` to internal URLs, and `http://169.254.169.254/…` are all fetched at
render time — LFI and SSRF from prompt-injected content, the same exposure as the
unguarded scraper (TL-08) but inside the PDF renderer. Separately, the bare-filename
image resolver globs **the entire `system-generated` tree**
([pdf_generator.py:390](../../../backend/src/ai/tools/documents/pdf_generator.py:390)),
so one tenant's report can embed another tenant's image by filename.

**Fix:** render with a fetcher that blocks `file:`/internal hosts (or `presentational_hints`
off + a null fetcher), sanitise the HTML, and scope image resolution to the run's own
artifacts.

### TL-56 — Every email tool lets the model override the mail server

**✅ Verified · High**

TL-04 records this for `email_send` (SMTP relay). The same
`params.get(...) or resolved.get(...)` precedence is in **all four** email tools for
`imap_host`, `smtp_host`, `email_address` **and** `password`
([email_tool.py:189](../../../backend/src/ai/tools/email/email_tool.py:189),
[:307](../../../backend/src/ai/tools/email/email_tool.py:307),
[:405](../../../backend/src/ai/tools/email/email_tool.py:405),
[:524](../../../backend/src/ai/tools/email/email_tool.py:524)). So `email_ingest`,
`email_classify` and `email_draft` will connect the tenant's **decrypted** password to a
model-chosen host — a credential-exfiltration path even on the read tools, not just a
send relay.

**Fix:** the same as TL-04, applied to the shared resolver: drop `imap_host`, `smtp_host`,
`email_address`, `password` from accepted params; resolve them only from the connection row.

### TL-57 — The email tools block the event loop

**✅ Verified · Medium**

`imaplib` and `smtplib` are synchronous and are called directly in the async handlers
([email_tool.py:96](../../../backend/src/ai/tools/email/email_tool.py:96),
[:103](../../../backend/src/ai/tools/email/email_tool.py:103)), with **no** socket
timeout. A slow or unreachable mail server stalls the whole worker for as long as the OS
TCP timeout. TL-32 flagged this for `video_generate`; the email tools have the same
problem and are far more likely to hang.

**Fix:** `asyncio.to_thread` the blocking calls and pass an explicit timeout.

### TL-58 — `email_classify` moves the wrong message

**✅ Verified · Medium**

`email_ingest` returns IMAP **sequence numbers** but labels them `uid`
([email_tool.py:246](../../../backend/src/ai/tools/email/email_tool.py:246)).
`email_classify` then `COPY`s that number and `store(+FLAGS \\Deleted)` + `expunge()`s it
([email_tool.py:339](../../../backend/src/ai/tools/email/email_tool.py:339)). Sequence
numbers **renumber after every expunge**, so classifying a batch moves the first message
correctly and then moves the *wrong* message for every subsequent call in the run. (It
also uses `COPY`+`EXPUNGE` rather than `UID MOVE`, the non-atomicity TL-39 notes.)

**Fix:** fetch and return real UIDs (`UID FETCH`), operate with `UID COPY`/`UID STORE`/
`UID EXPUNGE`, and prefer `UID MOVE` where the server supports it.

### TL-59 — Tool outputs are double-written and orphaned from their run

**✅ Verified · Medium**

`file_writer`, `docx_tool`, `pptx_tool`, `excel_tool`, `pdf_generator` and
`image_generation` write the file to a path **and then** call `save_artifact`, which
writes a **second** copy under a `uuid4_`-prefixed name
([artifact_service.py:74](../../../backend/src/ai/artifact_service.py:74)). The path the
tool returns to the model is the **unregistered** first copy; the registered artifact is a
different file on disk. Every `update`/`save_as` output is never registered at all. And of
these tools only `document_save`, `sandbox_code` and `scraper_tool` pass `run_id`/
`agent_id` — the rest register artifacts with `run_id=None`, so they never appear under
the run on the Execution Detail page (TL-46 notes this for video only).

**Fix:** one write path — hand the bytes to `save_artifact` and return its stored path and
id; always pass the run/agent ids from context.

### TL-60 — `batch_web_search` ignores its own contract

**✅ Verified · Medium**

`max_per_query` is advertised in the schema and parsed into `BatchWebSearchParams` but is
**never used** — every sub-query returns the underlying tool's default page
([batch_search.py:231](../../../backend/src/ai/tools/core/batch_search.py:231)). The
docstring and description promise **deduplicated** results, but `seen_urls` is initialised
and never read; nothing dedupes. And the cost path charges `batch_web_search` as a single
`serp-api-key` unit (TL-19) while it fans out to up to **25** real SerpAPI calls, so a
batch is under-billed ~25×.

**Fix:** honour `max_per_query`, dedupe on URL, and bill per sub-query executed.

### TL-61 — `sandbox_code` accepts an unbounded timeout from the model

**✅ Verified · Medium**

`terminal` and `headless_browser` cap the model-supplied timeout at 120 s
([terminal_tool.py:121](../../../backend/src/ai/tools/sandbox/terminal_tool.py:121),
[browser_tool.py:118](../../../backend/src/ai/tools/sandbox/browser_tool.py:118)).
`sandbox_code` takes `timeout_s` straight from the args with **no ceiling**
([sandbox_executor.py:96](../../../backend/src/ai/tools/sandbox/sandbox_executor.py:96)),
so one call can hold a worker for an arbitrary duration.

**Fix:** clamp `timeout_s` to the same 120 s ceiling (or the entity's
`max_execution_seconds`).

### TL-62 — `headless_browser` cannot chain actions

**✅ Verified · Medium**

Each call opens a fresh browser session, runs one action, and tears the session down
([browser_tool.py:151](../../../backend/src/ai/tools/sandbox/browser_tool.py:151)). There
is no persisted page between calls, so `click`/`type`/`get_text` that do not themselves
carry a `url` run against `about:blank` and fail; a login-then-read or click-through flow
is impossible. The tool advertises those actions as if they compose.

**Fix:** persist a page across calls within a run (keyed by run id), or document the tool
as single-shot navigation only and drop the stateful actions.

### TL-63 — `pdf_generator` defines `get_function_schema` twice

**✅ Verified · Low** · **Status: fixed (2026-10-01)** — the second copy is deleted; the
schema advertises `image_paths` again.

Two `get_function_schema` methods ([pdf_generator.py:76](../../../backend/src/ai/tools/documents/pdf_generator.py:76)
and [:715](../../../backend/src/ai/tools/documents/pdf_generator.py:715)); the second wins.
The first advertises `image_paths`, the second does not — so the model is never told about
the parameter the tool actually reads, and the schema/impl-drift test (TX-I9) would flag
it.

**Fix:** delete the stale copy, keep the one that advertises `image_paths`.

### TL-64 — The cost estimator's tool names don't match the registry

**✅ Verified · Low**

`planning/cost_estimator.TOOL_BASELINE_COST` keys on `excel`, `sandbox_executor`,
`browser_tool` and `xlsx_engine`
([cost_estimator.py:22](../../../backend/src/ai/planning/cost_estimator.py:22)); the
registered names are `excel_tool`, `sandbox_code`, `headless_browser` (and there is no
`xlsx_engine` tool). Those four estimates never match a real tool, so the planner's
`cost_estimate_within_budget` invariant uses the default for them. This is a fifth face of
the four-price-table problem (TL-19).

**Fix:** key on registry names; ideally derive from the one resolver (TL-19).

### TL-65 — `__is_meta_agent__` is never set, so its gates never see a real meta-agent

**✅ Verified · Medium**

`tool_synthesis` refuses unless `context["__is_meta_agent__"]` is truthy
([tool_synthesis.py:58](../../../backend/src/ai/tools/meta/tool_synthesis.py:58)), and
`meta_entity_creator` applies its runtime-creation limit to everyone for whom it is falsy
([entity_creator.py:92](../../../backend/src/ai/tools/meta/entity_creator.py:92)). But
**nothing in the codebase ever sets that key** — the only writers are a test and a
docstring; the meta-agent is flagged by `metadata_extensions.is_meta_agent` on the entity,
which never reaches the tool context. So `tool_synthesis` is unreachable for the genuine
Meta-Agent, and the only way to flip either gate is to inject the key through run input
(TL-53). The gate is both a dead end for the intended caller and a hole for everyone else.

**Fix:** derive `__is_meta_agent__` from the entity's `metadata_extensions.is_meta_agent`
when building tool context; never from run input.

### TL-66 — Three `ACTIVE` tools have no declared dependency

**✅ Verified · High (packaging)**

`pdf_generator` needs `weasyprint` + `markdown`; `headless_browser` needs `playwright`;
`web_search`'s free fallback needs `ddgs`/`duckduckgo_search`. **None of these four is in
`pyproject.toml`.** On a clean install all three tools are dead — `pdf_generator` and
`headless_browser` return "not installed" errors (and by TL-52 those errors are logged as
successes), and `web_search` silently loses its no-key fallback. Confirmed in the dev
`.venv`: `weasyprint`, `markdown`, `playwright`, `ddgs`, `duckduckgo_search` all fail to
import; three live `pdf_generator` calls failed for exactly this reason (§4).
`SESSION-HANDOFF.md` notes the local gap, but the root cause is that the deps are
undeclared, so it recurs on every fresh environment.

**Fix:** declare `weasyprint`, `markdown`, and the DuckDuckGo library in `pyproject.toml`;
decide whether `playwright` (+ browser install) belongs in the API image or only the
sandbox image, and make `headless_browser` say so when it is absent.

### TL-67 — Seeds and fixtures name tools that don't exist

**✅ Verified · Medium**

The deep-research seed and the test fixture grant `scraper`, `batch_search` and
`docx_generator` ([create_v2.py:334](../../../backend/scripts/seeds/deep_research/DeepResearchSetup/create_v2.py:334),
[:463](../../../backend/scripts/seeds/deep_research/DeepResearchSetup/create_v2.py:463);
[tests/fixtures/entities/research_agent.json:58](../../../backend/tests/fixtures/entities/research_agent.json:58)).
The registered names are `scraper_tool`, `batch_web_search` and `docx_tool` — there is no
`scraper`, `batch_search` or `docx_generator`. So a seeded research agent plans steps that
`ToolExecutor` cannot resolve; confirmed live — six `docx_generator` calls logged
`Error: Tool 'docx_generator' not found` (§4). This is what makes a fresh deep-research
run fail its DOCX step. (The planner's `all_required_tools_in_capabilities` invariant does
not catch it because the capability list contains the same wrong name.)

**Fix:** correct the names in the seed and fixture; add the schema/registry contract test
(TX-I9) so a capability naming an unregistered tool fails CI.

---

## 4. Live evidence (dev database, 2026-09-29)

Read-only queries against the running dev DB:

- **`tool_interaction_logs`, all time:** `docx_generator` — 6 calls, **0** success, all
  `Error: Tool 'docx_generator' not found` (TL-67). `pdf_generator` — 3 calls, all logged
  `success=True`, all with `{"error": "… weasyprint …"}` payloads (TL-52, TL-66).
  `research_gatherer` and `google:python_interpreter` — outputs overwritten with
  `[TOOL_EMPTY] … ERROR_MSG` (TL-51). `web_search→headless_browser` — a fallback fired.
- **Entities:** the only tool ids named across active entities are `web_search`,
  `scraper`, `batch_search`, `calculator`, `document_save`, `batch_web_search`,
  `pdf_generator`, `docx_generator` — i.e. real research agents are configured with the
  **wrong** names `scraper` / `batch_search` / `docx_generator` (TL-67). No entity uses any
  social, email, CRM or media tool.
- **`social_connections`:** empty. **`email_connections`:** empty. So no social/email tool
  can resolve a credential today — they all fall to their "not configured" branch.
- **`integration_registry` (non-LLM):** one row — a `google` embedding SKU. **No**
  `CUSTOM_API` priced row, and no `serp-api-key`/`firecrawl` row, so search and scrape have
  no key and no cost entry (TL-52/TL-19 mean those calls are billed $0 and logged success).
- **`feature_flags`:** empty — so every per-company flag (container runtime, resilience,
  cost resolver, experimental gates) resolves to its env/default, confirming the TX-01 and
  TL-13 outcomes.

---

## 5. What needs fixing — prioritised

The product owner asked for the list. Ordered by consequence, not effort. Items marked
**new** are from §3; the rest point to the existing register entry that owns them.

### Tier 0 — tenant boundary and untrusted code (before any paying tenant)

| # | Fix | Entry |
|---|---|---|
| 1 | Restrict execution to the entity's granted tools (and thread `company_id` through resolution) | **TL-50 (new)**, TL-10 |
| 2 | Stop trusting run input as tool context (`container_runtime`, `__is_meta_agent__`, `persona`, flags) | **TL-53 (new)**, **TL-65 (new)** |
| 3 | Confine every model-supplied file path to the tenant workspace; take sources as references | **TL-54 (new)**, TL-09, TL-17 |
| 4 | Block `file:`/internal fetches in `pdf_generator`; scope its image resolver to the run | **TL-55 (new)** |
| 5 | Resolve email host + credentials only from the connection row, on all four tools | **TL-56 (new)**, TL-04 |
| 6 | The existing T0 set: SSRF guard, symlink, registry read scoping, credential precedence | TL-01…TL-08, TX-01 |

### Tier 1 — correctness that silently corrupts results or money

| # | Fix | Entry |
|---|---|---|
| 7 | Don't fail a succeeding tool on output keywords; never re-run a write on retry | **TL-51 (new)** |
| 8 | Set `success` from the tool's error envelope; don't bill or "succeed" a failed call | **TL-52 (new)** |
| 9 | Fix `email_classify` to use real UIDs / `UID MOVE` | **TL-58 (new)** |
| 10 | One write path for tool outputs; always attach run/agent ids | **TL-59 (new)** |
| 11 | Honour `max_per_query`, dedupe, and bill per sub-query in `batch_web_search` | **TL-60 (new)** |
| 12 | Declare the missing deps; make absent tools say so | **TL-66 (new)** |
| 13 | Correct the seed/fixture tool names; add the registry contract test | **TL-67 (new)**, TX-I9 |
| 14 | The one enforcement point: status gate, `is_enabled`, cost resolver, rate limit | TL-11…TL-14, TL-19, TX-06 |

### Tier 2 — robustness and hygiene

| # | Fix | Entry |
|---|---|---|
| 15 | `asyncio.to_thread` the email + image blocking calls; add timeouts | **TL-57 (new)**, TL-32 |
| 16 | Cap `sandbox_code` timeout | **TL-61 (new)** |
| 17 | Persist a browser page across calls, or document single-shot | **TL-62 (new)** |
| 18 | Delete `pdf_generator`'s duplicate schema | **TL-63 (new)** |
| 19 | Key the cost estimator on registry names | **TL-64 (new)**, TL-19 |
| 20 | Deduplicate `_sandbox_base_dir` across `runtime.py`/`tenant_manager.py` | TL-29 (reworded) |

### Tier 3 — the social stack (this is where PO-07 begins)

| # | Fix | Entry |
|---|---|---|
| 21 | Delete `quora`, `x_ads`, `youtube_ads` (12 tools; fabricated/unworkable APIs) | TL-23, TL-24, TL-25 |
| 22 | Derive one platform list from tool ∩ connection ∩ refresh; build a connection UI | PO-07, TL-40 |
| 23 | Repair the T4 integrations before promoting any platform out of `EXPERIMENTAL` | TL-43…TL-49 |
| 24 | Retire, gate, or finish the rest — 64 unverified social tools cost more than the ~5 that will ship | TL-13, TX-I3 |

**The through-line:** the tool layer's four root faults (two registries that never meet,
tenancy-as-convention, policy-declared-nowhere-enforced, a four-path string contract) are
still the right frame — every new finding above is another face of one of them. The two
changes that retire the most defects at once remain the ones the deep register already
named: **one resolution entry point** (TL-10/TL-13/TL-14 + TL-50) and **one typed
execution path** (TL-41 + TL-51/TL-52/TL-59). Do those two and roughly half of this list —
old and new — collapses.

---

## Where to go next

- [`TOOL-LAYER-DEFECTS.md`](TOOL-LAYER-DEFECTS.md) — the 49-entry deep pass this audit
  re-verified and extends (TL-50…TL-67).
- [`09-TOOLS-DEFECTS.md`](09-TOOLS-DEFECTS.md) — the doc-09 additions (TX-01…TX-06) and
  improvements.
- [`01-PRODUCT-OVERVIEW-DEFECTS.md`](01-PRODUCT-OVERVIEW-DEFECTS.md) — PO-06 (this audit)
  and PO-07 (the social connection module).
- [`14-BILLING-AND-CREDITS-DEFECTS.md`](14-BILLING-AND-CREDITS-DEFECTS.md) — BC-07…BC-11
  for the cost-path defects TL-52/TL-60 touch.
