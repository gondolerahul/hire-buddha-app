# 12 — Where connected-account data goes (the data-flow note)

> **Written:** 29 Oct 2026, from the code at the wave 3 change of [10](10_code_fix_plan.md) · **For:** the CASA lab and Google's reviewers (GOOG-E6), Meta (META-E5), X (X-E4), LinkedIn (LI-E3), and the privacy policy of [11](11_website_content/hirebuddha.com/privacy.md)
> **What it is:** the written note GOOG-E6 asks for. Each statement names the code that makes it true, so a reviewer can check it and an engineer knows what a change must keep.

## 1. The path of one read

1. **A tool asks the broker.** An agent's tool (`social_api`, the e-mail tools, `google_drive`) gets its credential from `connections/client.py` `credentials_for`. The broker hands out a token only for a connection the business connected and shared with that agent (`connection_grants`), and records the use (`connection_audit`).
2. **The provider answers into the run.** The answer is the tool's result. Before the agent's model sees it, mail, comments, messages and documents are screened for prompt injection and quoted as untrusted (`ai/governance/untrusted.py`, SH-E3).
3. **The run is marked.** The tool executor records which connection the call read through (`connections/source_data.py`; table `connector_data_marks`, one row per run, connection and read). The mark carries the provider's rules from the connector's catalog entry (`retention`).
4. **It is kept where the run is kept.** The result lives in the run's tool log, trace spans, model prompts and answers, and the run's CORTEX working memory, all in **that business's own database** (Phase 14's tenant plane), as is the audit of the token's use. None of it is written to the control database: billing rows (`usage_logs`) record that a tool ran and what it cost, never what it returned.
5. **It goes when its time is up, or on disconnect.** An hourly job (`redact_connector_data`) replaces what a marked run read with a notice: LinkedIn after 23 hours, X after 23 hours, YouTube after 30 days (its analytics while the connection is valid). Disconnecting any connection brings its removal forward to the next pass. A business's other data follows the business: deleted on request, at disconnect (stored events, SH-E1) or when the business is erased ([phase 15, doc 13](../13_offboarding_and_erasure.md)).

## 2. What it is never used for

| Statement | Why it holds | Where |
|---|---|---|
| No AI model is trained or fine-tuned on it, ours (BabyBuddha included) or anyone's | No training, fine-tuning or dataset-export pipeline exists in the code. BabyBuddha is a research option (product road map E35), gated on explicit data-use permission; it is not built | — |
| It is not used across businesses | Every learning job runs per business, in that business's database: dreaming (`dreaming_cron_trigger`), critic calibration, skill promotion, prompt evolution (`ai/core/arq_jobs.py`, each through `_each_tenant`). The skill library reads tool names and outcomes, never content | `ai/core/arq_jobs.py`, `ai/meta/skill_library.py` |
| LinkedIn, X and YouTube data never reach records, exports or long-term memory | A run that read them may not write records: the records engine refuses its Data API token (`data_api/records.py` `_source_allows`). Reports and exports read records and run metadata only. The run records no episode (`ai/memory/run_memory.py` `record_episode`) | `connections/source_data.py` `records_refusal`, `keeps_no_memory` |
| HireBuddha's staff do not read it without the business's agreement | Staff working in a business see a marked run with its content withheld, unless the business has given time-boxed support access; every view is recorded and shown to the business | `auth/support_access.py`, Settings → Support access |
| Model providers do not train on it | Gemini is called through Vertex AI (Google Cloud's terms: customer data is not used to train Google's models) and Claude through Azure AI Foundry (no training on prompts or completions). **To confirm by the owner:** any direct OpenAI or Anthropic key in the integration registry is on an account with training off and zero retention where offered | `integration_registry` rows |
| WhatsApp messages are not used to train models | As above: nothing trains on any connector's data | — |

## 3. What a change must keep

* A new tool that reads through a connection gets its credential from `credentials_for`, never from a table of its own: that is what marks the run.
* A new store of run content (a new log, a cache, an export) is added to the removal in `source_data._redact_run`, or it does not hold connector content.
* A new learning or evaluation job runs per business and never reads a marked run's content across businesses. A job that would needs the owner's decision and an update to this note and to the privacy policy first.
* A provider's new rule goes into its connector's `retention` (catalog YAML), not into the tool.

## 4. Evidence for the lab

* The removal: `tests/integration/test_wave3_data_rules.py::test_a_linkedin_comment_is_gone_from_the_run_after_linkedins_limit`, with a LinkedIn comment in a tool log, a trace span, a prompt, a CORTEX node and the result.
* No records, no memory: `…::test_a_run_that_read_linkedin_saves_no_records_and_no_memory`.
* Staff access: `…::test_staff_see_the_content_only_under_the_business_grant`.
* Prompt injection: `tests/unit/test_connector_review_fixes.py` (the screening tests).
* Tenancy isolation: the isolation suite (`tests/isolation`) and `tests/unit/test_tenancy.py`.
