# 09. Tools & the Tool Registry — Defect Register

> **What this document is:** the tool-layer register at the level of
> [`09-tools.md`](../09-tools.md) — the registry, the contract, the catalogue, costing and
> the management API.
> **⚠️ This file is a summary and a set of additions. The authoritative deep pass is
> [`TOOL-LAYER-DEFECTS.md`](TOOL-LAYER-DEFECTS.md) — 49 verified defects across the same
> subsystem.** Do not fix from this file alone; open that one.
> **Compiled:** 2026-09-01, against branch `fresh-main`.

---

## How to read this file

The tool layer already has the deepest register in the set. Rather than restate its 49
entries, this file does three things:

1. **[§2](#2-what-the-deep-register-covers)** — maps `09-tools.md` onto the deep register
   so you can find the right entry from the document you were reading.
2. **[§3](#3-additions-not-in-the-deep-register)** — six defects found at doc-09 scope on
   2026-09-01 that the deep pass did not record. One of them
   ([TX-01](#tx-01--the-per-company-sandbox-flag-is-never-read)) materially changes how
   [TL-01](TOOL-LAYER-DEFECTS.md#tl-01--the-default-sandbox-runs-llm-authored-code-as-the-backend-os-user)
   should be fixed.
3. **[§4](#4-improvements)** — efficiency improvements, which the deep register does not
   cover. It is a defect list; this section is the other half of the brief.

Labels are the same: **✅ Verified** means the code was read on 2026-09-01.

---

## Contents

1. [Summary](#1-summary)
2. [What the deep register covers](#2-what-the-deep-register-covers)
3. [Additions not in the deep register](#3-additions-not-in-the-deep-register)
4. [Improvements](#4-improvements)
5. [Suggested order of work](#5-suggested-order-of-work)

---

## 1. Summary

| Source | Count |
|---|---|
| [`TOOL-LAYER-DEFECTS.md`](TOOL-LAYER-DEFECTS.md) — the deep pass | **49 defects**, all verified |
| This file — additions at doc-09 scope | **6 defects** |
| This file — efficiency improvements | **10** |

The four root faults from the deep register still hold and are the right frame for all
55 defects:

| Fault | One line |
|---|---|
| **A** | Two registries that never meet — the in-code one and `tool_registry_entries` |
| **B** | Tenancy is a convention, not a boundary |
| **C** | Policy declared in one place, enforced in none |
| **D** | The contract is a string with four dispatch paths |

[TX-01](#tx-01--the-per-company-sandbox-flag-is-never-read) below is a fifth instance of
fault **C**, and the most consequential one found since.

---

## 2. What the deep register covers

Use this to jump from a section of `09-tools.md` to the entry that describes what is
wrong with it.

| `09-tools.md` section | Deep register entries |
|---|---|
| §2 The tool registry | [TL-10](TOOL-LAYER-DEFECTS.md#tl-10--tenant-scoped-tools-are-unreachable-by-construction), [TL-13](TOOL-LAYER-DEFECTS.md#tl-13--the-tool-status-gate-is-not-wired-into-execution), [TL-14](TOOL-LAYER-DEFECTS.md#tl-14--is_enabled--false-does-not-disable-anything), [TL-34](TOOL-LAYER-DEFECTS.md#tl-34--metadata-drift-between-code-and-db-is-permanent-by-design) |
| §3 The tool contract | [TL-05](TOOL-LAYER-DEFECTS.md#tl-05--the-typed-dispatch-path-silently-drops-execution-context-in-scraper_tool), [TL-30](TOOL-LAYER-DEFECTS.md#4-t2--delete), [TL-41](TOOL-LAYER-DEFECTS.md#tl-41--four-dispatch-paths-and-the-typed-one-fails-silently) |
| §5 The catalogue | [TL-23](TOOL-LAYER-DEFECTS.md#4-t2--delete) to [TL-27](TOOL-LAYER-DEFECTS.md#4-t2--delete), [TL-35](TOOL-LAYER-DEFECTS.md#tl-35--_builtin_categories-covers-22-of-98-tools) |
| §7 `documents/` | [TL-03](TOOL-LAYER-DEFECTS.md#tl-03--llm-supplied-company_id-is-accepted-as-the-tenant-boundary), [TL-26](TOOL-LAYER-DEFECTS.md#4-t2--delete), [TL-27](TOOL-LAYER-DEFECTS.md#4-t2--delete) |
| §8 `email/` | [TL-04](TOOL-LAYER-DEFECTS.md#tl-04--email_send-lets-the-model-override-the-smtp-server-and-password), [TL-09](TOOL-LAYER-DEFECTS.md#tl-09--subject-data-is-model-chosen-with-no-ownership-check), [TL-39](TOOL-LAYER-DEFECTS.md#tl-39--no-idempotency-on-any-write-tool) |
| §9 `media/` | [TL-17](TOOL-LAYER-DEFECTS.md#tl-17--the-video-tools-write-outside-the-bind-mount), [TL-31](TOOL-LAYER-DEFECTS.md#tl-31--the-accurate-trim-fallback-in-_ffmpeg-raises-valueerror), [TL-32](TOOL-LAYER-DEFECTS.md#tl-32--blocking-sdk-calls-on-the-event-loop-in-video_generate), [TL-46](TOOL-LAYER-DEFECTS.md#tl-46--video_generate-ignores-is_audio_required-and-reports-it-back) |
| §10 `social/` | [TL-37](TOOL-LAYER-DEFECTS.md#tl-37--the-social-base-class-never-retries-429-or-5xx), [TL-38](TOOL-LAYER-DEFECTS.md#tl-38--no-pagination-in-any-social-list-call), [TL-40](TOOL-LAYER-DEFECTS.md#tl-40--eight-of-sixteen-platforms-cannot-refresh-their-tokens), and all of [T4](TOOL-LAYER-DEFECTS.md#6-t4--integrations-that-report-false-success) |
| §12 `sandbox/` | [TL-01](TOOL-LAYER-DEFECTS.md#tl-01--the-default-sandbox-runs-llm-authored-code-as-the-backend-os-user), [TL-07](TOOL-LAYER-DEFECTS.md#tl-07--a-process-global-symlink-points-at-whichever-tenant-ran-last), [TL-15](TOOL-LAYER-DEFECTS.md#tl-15--networkpolicy-and-the-egress-proxy-are-wired-to-nothing), [TL-16](TOOL-LAYER-DEFECTS.md#tl-16--the-tenant-workspace-lives-in-tmp-and-is-node-local), [TL-18](TOOL-LAYER-DEFECTS.md#tl-18--chromium-never-enters-the-container), [TL-36](TOOL-LAYER-DEFECTS.md#tl-36--terminal-scans-all-of-tmp-and-mis-attributes-artifacts), [TL-42](TOOL-LAYER-DEFECTS.md#tl-42--the-terminal-blocklist-is-a-speed-bump-not-a-boundary), plus [TX-01](#tx-01--the-per-company-sandbox-flag-is-never-read) below |
| §13 `meta/` | [TL-02](TOOL-LAYER-DEFECTS.md#tl-02--tool-synthesis-executes-generated-code-outside-the-sandbox) |
| §14 `mcp/` | [TL-22](TOOL-LAYER-DEFECTS.md#tl-22--the-mcp-layer-has-no-transport-no-config-and-no-caller) |
| §15 `resilience.py` | [TL-37](TOOL-LAYER-DEFECTS.md#tl-37--the-social-base-class-never-retries-429-or-5xx), [TL-39](TOOL-LAYER-DEFECTS.md#tl-39--no-idempotency-on-any-write-tool), and [EP-22](06-EXECUTION-PIPELINE-DEFECTS.md#ep-22--with-the-resilience-flag-off-react-tool-calls-get-no-healing-at-all) |
| §17 Budgets and rate limits | [TL-11](TOOL-LAYER-DEFECTS.md#tl-11--the-only-enforced-rate-limit-is-never-populated), [TL-12](TOOL-LAYER-DEFECTS.md#tl-12--the-per-tool-permission-model-sits-on-a-class-nothing-uses), [TL-21](TOOL-LAYER-DEFECTS.md#tl-21--max_tool_calls-is-a-prompt-string-not-a-limit), [TL-28](TOOL-LAYER-DEFECTS.md#4-t2--delete) |
| §18 Costing | [TL-19](TOOL-LAYER-DEFECTS.md#tl-19--four-price-tables-one-of-which-is-the-unused-source-of-truth), [TL-20](TOOL-LAYER-DEFECTS.md#tl-20--voice-tool-calls-are-unattributed-and-unbilled), [TL-33](TOOL-LAYER-DEFECTS.md#tl-33--a-registry-select-per-tool-call-inside-the-react-loop) |
| §19 Management API | [TL-06](TOOL-LAYER-DEFECTS.md#tl-06--the-tool-registry-read-endpoints-return-every-tenants-rows), [TL-14](TOOL-LAYER-DEFECTS.md#tl-14--is_enabled--false-does-not-disable-anything), [TL-34](TOOL-LAYER-DEFECTS.md#tl-34--metadata-drift-between-code-and-db-is-permanent-by-design), [TL-35](TOOL-LAYER-DEFECTS.md#tl-35--_builtin_categories-covers-22-of-98-tools) |
| §20 Security review | All of [T0](TOOL-LAYER-DEFECTS.md#2-t0--tenant-boundary-and-untrusted-code) |

---

## 3. Additions not in the deep register

### TX-01 — The per-company sandbox flag is never read

**✅ Verified · Critical**

This one changes how [TL-01](TOOL-LAYER-DEFECTS.md#tl-01--the-default-sandbox-runs-llm-authored-code-as-the-backend-os-user)
should be fixed, so read it before starting that work.

`sandbox.container_runtime_enabled` is declared in `DEFAULTS` with a value of **`True`**
and a comment saying it is "globally enabled as of Phase 12 go-live". An operator reading
the admin Feature Flags page sees container sandboxing switched on.

The runtime decides differently:

```python
def _container_runtime_selected(context):
    if context is not None and "container_runtime" in context:
        return bool(context["container_runtime"])
    return bool(settings.SANDBOX_CONTAINER_RUNTIME_ENABLED)   # default False
```

The flag reaches this function **only** through `context["container_runtime"]`. Grepping
the whole backend for `container_runtime` outside `runtime.py` and `container_runtime.py`
returns exactly one line: the flag's own declaration in `feature_flags.py`.

**No caller ever threads it into the tool context.** So the per-company flag is inert, and
the only thing that decides is `settings.SANDBOX_CONTAINER_RUNTIME_ENABLED`, which
defaults to `False`.

Net effect: the feature flag says container sandboxing is on, the code default says it is
off, off wins, and LLM-authored code runs as the backend OS user — exactly the situation
TL-01 describes, but with an extra layer of misleading configuration on top.

- [`ai/core/feature_flags.py:102`](../../../backend/src/ai/core/feature_flags.py:102) — the flag, default `True`
- [`ai/tools/sandbox/runtime.py:285`](../../../backend/src/ai/tools/sandbox/runtime.py:285) — `_container_runtime_selected`
- [`common/config.py`](../../../backend/src/common/config.py) — `SANDBOX_CONTAINER_RUNTIME_ENABLED = False`

**Fix:** thread the resolved per-company flag into the tool context, **or** delete the
flag and use the setting alone. Do not leave two switches where one is invisible and the
visible one is a lie. This is a prerequisite for the TL-01 fix, alongside
[TL-16](TOOL-LAYER-DEFECTS.md#tl-16--the-tenant-workspace-lives-in-tmp-and-is-node-local).

---

### TX-02 — Tool instances are process-wide singletons

**✅ Verified · High**

`ToolRegistry.register(tool)` stores the **instance**: `cls._tools[tool.name] = tool`.
There is one object per tool for the life of the process, shared by every concurrent run
of every tenant.

Any tool that assigns per-call state to `self` — a company id, a resolved credential, a
working directory, an HTTP client bound to one tenant's token — leaks that state across
concurrent runs.

Nothing in the base class prevents it and nothing in review catches it. The tools README
warns about it in prose; the type system does not.

- [`ai/tools/base.py`](../../../backend/src/ai/tools/base.py) — `ToolRegistry.register`

**Fix:** make the registry store a factory, or freeze the instance after registration so
an attribute write raises. The second is a few lines and catches the mistake at the moment
it happens.

---

### TX-03 — `usage: "PLANNED"` hides a tool from the model but not from execution

**📄 Doc-reported · Medium**

Tools declared `usage: "PLANNED"` are excluded from the LLM prompt — only `AUTONOMOUS` and
`BOTH` are injected. But a `PLANNED` tool named directly in a static plan step executes
normally.

So "not advertised" and "not callable" are the same word, and the safer-sounding value is
the one that offers no protection.

- [`ai/step_executor.py:725`](../../../backend/src/ai/step_executor.py:725)

**Fix:** split into two flags — `llm_callable` and `plan_callable`. Recorded in the deep
register as part of [TL-12](TOOL-LAYER-DEFECTS.md#tl-12--the-per-tool-permission-model-sits-on-a-class-nothing-uses);
noted here because the `usage` field is what an entity author actually sets.

---

### TX-04 — `meta_spec_critic` is a `Tool` that is not in the registry

**📄 Doc-reported · Low**

It is instantiated directly rather than registered, so `ToolRegistry.get_tool` will never
find it. Anyone auditing "which tools can run" from the registry will miss it, and anyone
looking for it by name will conclude it does not exist.

- [`ai/tools/meta/spec_critic.py`](../../../backend/src/ai/tools/meta/spec_critic.py)

---

### TX-05 — `register_tenant_tool` logs at INFO on every registration

**✅ Verified · Low**

`logger.info(f"Registered tenant tool '{tool.name}' for company {cid}")` fires on every
tenant tool registration. Since tenant tools are registered per process and lost on
restart ([TL-10](TOOL-LAYER-DEFECTS.md#tl-10--tenant-scoped-tools-are-unreachable-by-construction)),
a busy multi-worker deployment writes this line repeatedly for tools that are then never
reachable.

Minor on its own; listed because the log line is the main evidence an operator has that
tenant tools "work".

- [`ai/tools/base.py`](../../../backend/src/ai/tools/base.py) — `register_tenant_tool`

---

### TX-06 — `get_tools_for_company` merges correctly and has no execution caller

**✅ Verified · Medium**

`ToolRegistry` has three lookup methods:

| Method | Takes `company_id` | Called from the execution path |
|---|---|---|
| `get_tool` | optional | yes — but **always without it** |
| `get_tools_for_company` | required | **no** |
| `get_visible_tools_for_company` | required | **no** — only a unit test |

So the registry offers two correct, tenant-aware lookups and the executor uses neither.
This is the mechanical root of fault **A** and of
[TL-10](TOOL-LAYER-DEFECTS.md#tl-10--tenant-scoped-tools-are-unreachable-by-construction):
the capability exists at the registry and is not reached from the caller.

- [`ai/tools/base.py`](../../../backend/src/ai/tools/base.py) — the three methods
- [`ai/tool_executor.py`](../../../backend/src/ai/tool_executor.py) — the caller

---

## 4. Improvements

The deep register is a defect list. These are the efficiency items.

### TX-I1 — Cache tool prices per run

**Effect: large.** Both cost blocks run an `IntegrationRegistry` query for **every tool
result**, inside the per-turn loop, with no caching
([TL-33](TOOL-LAYER-DEFECTS.md#tl-33--a-registry-select-per-tool-call-inside-the-react-loop)).
A research agent doing 25 searches issues 25 round trips for a value that changes daily.

`ToolCostResolver` already has the cache and has zero call sites
([TL-19](TOOL-LAYER-DEFECTS.md#tl-19--four-price-tables-one-of-which-is-the-unused-source-of-truth)).
Wiring it fixes the price-table sprawl and the query storm in one change.

### TX-I2 — One dispatch path, schema derived from the params model

**Effect: large.** Today a tool can be entered four ways, structured arguments are
serialised to JSON and re-parsed inside each tool, and a large fraction of tool code is
defensive parsing — `pdf_generator` is 746 lines, most of it input rescue.

One `execute(params: ParamsModel, ctx: ExecutionContext) -> ToolOutput` with the JSON
schema generated from the model removes the parsing code, makes schema/implementation
drift impossible, and closes
[TL-05](TOOL-LAYER-DEFECTS.md#tl-05--the-typed-dispatch-path-silently-drops-execution-context-in-scraper_tool),
[TL-30](TOOL-LAYER-DEFECTS.md#4-t2--delete) and
[TL-41](TOOL-LAYER-DEFECTS.md#tl-41--four-dispatch-paths-and-the-typed-one-fails-silently)
together.

### TX-I3 — Delete twelve tools before optimising anything

**Effect: large, and it is a deletion.** `quora` (4), `x_ads` (4) and `youtube_ads` (4) are
written against APIs that do not exist or cannot work as coded. Removing them takes the
registry from 98 tools to 86 and removes ~1,600 lines with `xlsx_engine.py` and the docx
templates.

Every subsequent change to the tool layer costs less afterwards.

### TX-I4 — Make the registry store factories, not instances

**Effect: medium.** [TX-02](#tx-02--tool-instances-are-process-wide-singletons). A factory
per tool removes a whole class of concurrency bug and makes per-call state safe to write —
which in turn makes the tools much simpler, since today they must thread everything
through arguments to avoid `self`.

### TX-I5 — Retry 429 and 5xx in the social base class

**Effect: medium.** `_api_request` re-raises **every** `httpx.HTTPStatusError`
immediately, with a comment saying "Don't retry client errors" — but the `except` catches
all status errors, so 429 and 5xx are never retried
([TL-37](TOOL-LAYER-DEFECTS.md#tl-37--the-social-base-class-never-retries-429-or-5xx)).

That is exactly the class of error social APIs return under load. The correct exponential
backoff already exists in `core/search.py`; reuse it.

### TX-I6 — Add pagination to social list calls

**Effect: medium.** Every `list` / `search` / `get_*` across all 16 platforms returns page
one and reports it to the model as the complete set
([TL-38](TOOL-LAYER-DEFECTS.md#tl-38--no-pagination-in-any-social-list-call)). The model
then reasons over a truncated set with no signal that it is truncated — which is worse
than an error, because the run completes with a confident wrong answer.

### TX-I7 — Idempotency keys on every write tool

**Effect: large for correctness under retry.** No social, email, CRM or media tool carries
one. Combined with the resilience layer's reformat-retry and fallback chain, a retried
step re-posts, re-sends and re-creates campaigns
([TL-39](TOOL-LAYER-DEFECTS.md#tl-39--no-idempotency-on-any-write-tool)).

The `idempotency_key` column already exists on `tool_interaction_logs` and is dead
([EP-14](06-EXECUTION-PIPELINE-DEFECTS.md#4-t2--dead-columns-and-dead-docs)). Use it.

### TX-I8 — Derive tool categories from the package

**Effect: small.** `_BUILTIN_CATEGORIES` is a hand-written map covering 22 of 98 tools; the
other 76 fall through to `general`, and the frontend offers a `social` filter that matches
nothing ([TL-35](TOOL-LAYER-DEFECTS.md#tl-35--_builtin_categories-covers-22-of-98-tools)).

The subpackage already *is* the category. Derive it and delete the map.

### TX-I9 — A contract test over every registered tool

**Effect: large for confidence.** Three separate defects —
[TL-43](TOOL-LAYER-DEFECTS.md#tl-43--youtube_upload_video-never-uploads-the-video),
[TL-46](TOOL-LAYER-DEFECTS.md#tl-46--video_generate-ignores-is_audio_required-and-reports-it-back)
and [TL-47](TOOL-LAYER-DEFECTS.md#tl-47--linkedin_create_post-advertises-image_url-and-never-reads-it)
— are the same bug: the advertised schema promises a parameter the code never reads.

One test that walks the registry and asserts every advertised parameter is referenced in
the implementation would have caught all three, and will catch the next one.

### TX-I10 — Async the blocking SDK calls

**Effect: medium.** `video_generate` calls four synchronous SDK methods directly in an
async handler, stalling the worker for the full length of a Veo generation — up to the
360-second poll ceiling
([TL-32](TOOL-LAYER-DEFECTS.md#tl-32--blocking-sdk-calls-on-the-event-loop-in-video_generate)).

`asyncio.to_thread` around each one frees the worker to do everything else. This is one of
the highest ratios of throughput gained to lines changed anywhere in the codebase.

---

## 5. Suggested order of work

Follow [`TOOL-LAYER-DEFECTS.md` §7](TOOL-LAYER-DEFECTS.md#7-suggested-execution-order) —
it is the sequenced plan for this subsystem. Two amendments from this file:

| Amendment | Detail |
|---|---|
| **Before step 5 (sandbox hardening)** | Fix [TX-01](#tx-01--the-per-company-sandbox-flag-is-never-read). Flipping the container default while the per-company flag is unread means the flag stays a lie in the other direction |
| **Add to step 6 (one resolution entry point)** | [TX-02](#tx-02--tool-instances-are-process-wide-singletons) and [TX-06](#tx-06--get_tools_for_company-merges-correctly-and-has-no-execution-caller). Both are registry changes and belong in the same commit |

For the improvements, the cheap-and-large ones are
[TX-I3](#tx-i3--delete-twelve-tools-before-optimising-anything) (deletion),
[TX-I10](#tx-i10--async-the-blocking-sdk-calls) (four `to_thread` calls) and
[TX-I1](#tx-i1--cache-tool-prices-per-run) (wire the resolver that already exists).

---

## Where to go next

- [`TOOL-LAYER-DEFECTS.md`](TOOL-LAYER-DEFECTS.md) — **the authoritative register for this
  subsystem.**
- [09 — Tools & the tool registry](../09-tools.md) — the source document.
- [06 — Execution pipeline](06-EXECUTION-PIPELINE-DEFECTS.md) — EP-02, EP-07, EP-22 for
  the executor side.
- [14 — Billing & credits](14-BILLING-AND-CREDITS-DEFECTS.md) — where the four price
  tables are meant to converge.
- [15 — Governance & HITL](15-GOVERNANCE-AND-HITL-DEFECTS.md) — the feature-flag service
  behind TX-01.
- [18 — Infrastructure](18-INFRASTRUCTURE-AND-DEPLOYMENT-DEFECTS.md) — building the
  `hb-sandbox` and `hb-egress-proxy` images.
