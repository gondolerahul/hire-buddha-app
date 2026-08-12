# `tools/` — Tool registry + resilience + per-tool implementations

Every action the agent takes that isn't pure LLM thinking is a Tool.
Tools are registered at import time and looked up by name.

## What's in here

| File / package | Purpose |
|----------------|---------|
| `base.py` | `Tool` abstract base, `ToolRegistry`, `ToolStatus` enum (ACTIVE / EXPERIMENTAL / DEPRECATED), `ToolRegistry.get_visible_tools_for_company(...)` that filters EXPERIMENTAL tools without the `tools.experimental.{tool_id}` opt-in flag. |
| `resilience.py` | Phase 11 Track 8 `ToolResilience` — shared reformat-retry + fallback chain wrapper for direct TOOL_CALL and REACT paths. `FailureKind` + `classify_tool_failure()`. |
| `meta/spec_critic.py` | Phase 11 Track 5 `meta_spec_critic` tool — reviews draft entity specs using anti-patterns from `MetaIntelligenceTree` and a different-model LLM call. |

## Subpackage layout (Phase 12 cut C8)

Tool implementations are grouped by subdomain. Only `__init__.py`, `base.py`,
and `resilience.py` live at the `tools/` root; everything else is in a
subpackage:

| Subpackage | Tools |
|------------|-------|
| `core/` | `calculator`, `search`, `batch_search`, `scraper`, `file_writer` |
| `documents/` | `pdf_generator`, `docx_tool`, `pptx_tool`, `excel`, `xlsx_engine`, `document_save` |
| `media/` | `image_generation`, `video_generation` (the `video_generation` split into generate/edit/sound is a separate cut — see `docs/phase12/plans/03_*`) |
| `sandbox/` | `sandbox_executor`, `sandbox_provision`, `terminal_tool`, `browser_tool` (per-tenant container runtime is `docs/phase12/plans/02_*`) |
| `email/` | `email_tool` |
| `crm/` | `crm_tools` |
| `social/` | 15 social + ads platform integrations |
| `meta/` | Meta-Agent tools (`platform_introspect`, `registry_search`, `schema_validator`, `entity_creator`, `entity_executor`, `spec_critic`) |

`tools/__init__.py` imports each implementation from its subpackage and
registers it; the registry API and all `from src.ai.tools import <ToolClass>`
re-exports are unchanged.

### Social/ads audit (C8)

The 15 `social/` platform integrations (LinkedIn, Twitter/X, Facebook,
Instagram, YouTube, TikTok, Reddit, Quora, Pinterest + the *Ads* variants for
Google/Meta/LinkedIn/YouTube/X/Snapchat) are **not yet wired to any production
entity** and several are unfinished. They are tagged
`ToolStatus.EXPERIMENTAL` on the `SocialMediaTool` base class, so they only
appear for a company that sets `tools.experimental.{tool_id}=true` (enforced by
`ToolRegistry.get_visible_tools_for_company`). Promote an individual platform
to `ToolStatus.ACTIVE` on its subclass once it is verified end-to-end. None
were deleted — "DEAD" classification needs real usage telemetry first.

### Deferred (follow-up)

Nesting `social/` under `tools/integrations/social/` and splitting the six
Ads platforms into `tools/integrations/ads/` (per `docs/phase12/plans/01` §5)
is deferred: the social modules use absolute intra-package imports (33 sites),
so the relocation is pure churn with no behaviour/clarity gain beyond the
nesting. It can land later as a self-contained rename.

## Key types

- `Tool`, `ToolParams`, `ToolResult`.
- `ToolStatus` (ACTIVE / EXPERIMENTAL / DEPRECATED).
- `ToolRegistry` (global + tenant-scoped).
- `FailureKind`, `ToolResilience`.

## Entry points

- `ToolRegistry.register(tool)` at import time.
- `ToolExecutor.execute_tools([{...}], extra_context=...)` is the leaf executor.
- Production code should call `ToolResilience.run(...)` (via `step_executor._execute_tool_call`) rather than `ToolExecutor` directly.

## See also

- `docs/phase11/plan/10_track_8_tool_and_cost.md`
- `docs/phase11/plan/07_track_5_meta_agent_board.md` — `meta_spec_critic`.
