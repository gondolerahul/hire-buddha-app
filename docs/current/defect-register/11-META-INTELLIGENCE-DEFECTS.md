# 11. Meta-Intelligence & the Meta-Agent Board — Defect Register

> **What this document is:** defects in the layer that lets the platform reason about and
> change itself — the seven-role Architecture Board, anti-sprawl, tool synthesis, prompt
> evolution and the MetaIntelligenceTree — plus the improvements that would make it safer
> and cheaper.
> **Source document:** [`11-meta-intelligence.md`](../11-meta-intelligence.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`.
> **Context:** this is the layer that creates entities and writes tools. Its safety model
> is a chain of gates, and **several of those gates fail open** — an exception in the
> checker is treated as "allowed".

---

## How to read this file

- **✅ Verified** — the code was read on 2026-09-01 and the claim held.
- **📄 Doc-reported** — from `11-meta-intelligence.md`, not independently re-checked.
- The safety model here is explicitly documented as gated. What follows is a list of the
  places where a gate is advisory, fails open, or is checking the wrong thing. Read
  [§2](#2-t0--gates-that-do-not-gate) before trusting any row in the safety table of
  `11-meta-intelligence.md` §19.

---

## Contents

1. [Summary](#1-summary)
2. [T0 — Gates that do not gate](#2-t0--gates-that-do-not-gate)
3. [T1 — Roles that do not do their job](#3-t1--roles-that-do-not-do-their-job)
4. [T2 — Wiring and documentation errors](#4-t2--wiring-and-documentation-errors)
5. [T3 — Silent data loss and tuning traps](#5-t3--silent-data-loss-and-tuning-traps)
6. [Improvements](#6-improvements)
7. [Suggested order of work](#7-suggested-order-of-work)

---

## 1. Summary

| Tier | Theme | Count | When to do it |
|---|---|---|---|
| [T0](#2-t0--gates-that-do-not-gate) | Gates that do not gate | 5 | Before enabling any autonomous creation |
| [T1](#3-t1--roles-that-do-not-do-their-job) | Roles that do not do their job | 4 | Before relying on the Board |
| [T2](#4-t2--wiring-and-documentation-errors) | Wiring and documentation errors | 5 | Now — mostly one-line |
| [T3](#5-t3--silent-data-loss-and-tuning-traps) | Silent data loss and tuning traps | 5 | When the area is next touched |

**Total: 19 defects, 10 improvements.**

The three to read first:

- **[MI-01](#mi-01--the-duplicate-check-fails-open)** — the semantic duplicate gate
  returns "not a duplicate" on any exception.
- **[MI-02](#mi-02--antisprawlguard-advises-and-only-one-caller-listens)** — the
  anti-sprawl guard does not block; a single caller chooses to honour it.
- **[MI-06](#mi-06--the-architect-cannot-revise-so-the-critic-loop-cannot-converge)** —
  the role responsible for acting on critic feedback appends a note and returns.

---

## 2. T0 — Gates that do not gate

### MI-01 — The duplicate check fails open

**✅ Verified · High**

`check_semantic_duplicate` ends with:

```python
except Exception as e:
    logger.warning(f"Semantic duplicate check failed: {e}. Allowing creation.")
    return {"is_duplicate": False, ...}
```

Any exception — a registry-search failure, an embedding error, a database blip — is
reported as "no duplicate found" and creation proceeds.

The Curator compounds it: both anti-sprawl calls are wrapped in
`except Exception: pass`. So if the registry search breaks, duplicate protection
disappears silently and entity sprawl resumes with no signal anywhere.

- [`ai/meta/anti_sprawl.py:157`](../../../backend/src/ai/meta/anti_sprawl.py:157)
- [`ai/meta/board/curator.py`](../../../backend/src/ai/meta/board/curator.py)

**Fix:** fail closed. A gate that cannot evaluate should refuse, not permit. If that is
too strict for a background job, at minimum emit a metric so a broken gate is visible.

---

### MI-02 — `AntiSprawlGuard` advises, and only one caller listens

**📄 Doc-reported · High**

The guard returns a decision. It does not block anything. Enforcement depends entirely on
`MetaEntityCreatorTool` choosing to honour the result.

Any other creation path — the ordinary `POST /ai/entities`, a seed script, a clone —
bypasses all three anti-sprawl gates completely.

So the daily limit, the adaptation-chain check and the semantic duplicate check apply to
exactly one of several ways an entity can be created.

- [`ai/meta/anti_sprawl.py`](../../../backend/src/ai/meta/anti_sprawl.py)
- [`ai/tools/meta/entity_creator.py`](../../../backend/src/ai/tools/meta/entity_creator.py) — the only enforcer

**Fix:** move the check into the entity-creation service, so every path goes through it.

---

### MI-03 — The daily creation limit is company-wide with no rate limit

**📄 Doc-reported · Medium**

The limit is 10 entities per company per rolling 24 hours. It is not per user and not
rate-limited within the window, so **ten entities can be created in ten seconds** and then
nothing for a day.

For a runaway Meta-Agent loop that is exactly the wrong shape: the burst is unconstrained
and the recovery is slow.

---

### MI-04 — Promoter gate G5 accepts any curator decision

**✅ Verified · Medium**

```python
d = getattr(decision, "decision", None)
return PromoterGateResult("G5_curator_recorded", passed=bool(d), reason="Curator decision missing" if not d else "")
```

The gate is named `G5_curator_recorded` and it checks only that a decision **exists**. A
curator decision of `CREATE` when the correct answer was `REUSE` passes identically to a
correct one.

So one of the six promotion gates is a presence check, not a correctness check — and the
name does say so, which makes it easy to over-read in the safety table.

- [`ai/meta/board/promoter.py:143`](../../../backend/src/ai/meta/board/promoter.py:143)

---

### MI-05 — A skipped test case is not a failed one

**📄 Doc-reported · Medium**

The TestDriver runs a budget-bounded five-case suite. A suite that runs out of budget and
**skips** cases can still report `passed=True`.

Promoter gate G4 is what catches this. So the safety of the whole promotion path depends on
one gate correctly distinguishing "passed" from "did not run", and the suite result itself
is misleading if read directly.

- [`ai/meta/board/test_driver.py`](../../../backend/src/ai/meta/board/test_driver.py)
- [`ai/meta/board/promoter.py`](../../../backend/src/ai/meta/board/promoter.py) — `_g4`

**Fix:** make `passed` mean "all cases ran and passed". Report skips as a separate field.

---

## 3. T1 — Roles that do not do their job

### MI-06 — The Architect cannot revise, so the critic loop cannot converge

**✅ Verified · High**

`Architect.revise` is the role that acts on critic feedback. The base implementation:

```python
new_payload = dict(draft.payload)
meta = dict(new_payload.get("metadata_extensions") or {})
revs = list(meta.get("architect_revisions") or [])
revs.extend(concerns)
meta["architect_revisions"] = revs
```

It appends the concerns to metadata and returns. **Nothing is rewritten.** The docstring is
honest — "Override to call a real LLM for an intelligent rewrite" — and no subclass does.

So the two-round critic loop critiques a draft, hands it to the Architect, gets back the
identical draft with a note attached, and critiques it again. The expected outcome is
`BLOCK` with *"max revise rounds reached"*.

- [`ai/meta/board/architect.py`](../../../backend/src/ai/meta/board/architect.py) — `revise`

**Fix:** either wire the Meta-Agent runtime entity in as the rewriter, or stop running the
revise loop — three critiques that cannot change anything is three LLM calls per attempt
for no benefit.

---

### MI-07 — `MAX_REVISE_ROUNDS = 2` means three critiques

**📄 Doc-reported · Medium**

The loop is `range(max_rounds + 1)`. So the constant named "max revise rounds" produces one
more critique than it reads as.

Combined with [MI-06](#mi-06--the-architect-cannot-revise-so-the-critic-loop-cannot-converge),
that is three billed critic calls per spec, all of which see the same draft.

- [`ai/meta/board/critic.py`](../../../backend/src/ai/meta/board/critic.py)

---

### MI-08 — Five of seven Board roles never call an LLM

**📄 Doc-reported · Low**

Only the Critic and (potentially) the Architect call a model; the TestDriver spends by
executing. The other five are deterministic.

That is a good design — it is recorded here because "seven-role board" reads as seven
reasoning agents, and both the cost model and the failure modes are quite different from
that.

---

### MI-09 — Semantic similarity alone can never trigger reuse

**📄 Doc-reported · Medium**

Semantic score carries weight 0.35 in the four-phase scorer, and the ADAPT threshold is
0.60. A **perfect** semantic match therefore scores 0.35 and falls short.

So the reuse engine cannot recommend reuse on semantic grounds alone, no matter how
identical the request. Reuse requires the other signals — name, tags, tool overlap — to
agree.

That may be intentional, but it means the semantic search that costs an embedding call on
every request cannot by itself change any decision.

- [`ai/meta/registry_search_service.py`](../../../backend/src/ai/meta/registry_search_service.py) — weights and thresholds

---

## 4. T2 — Wiring and documentation errors

| ID | Problem | Notes | Status |
|---|---|---|---|
| **MI-10** | Curator ↔ anti-sprawl key mismatch | The guard returns `existing_entity_id`; the Curator reads `dup.get('similar_id','?')`. The rationale shown to a human **always displays `?`** instead of the duplicate's id — which is the one piece of information the reviewer needs | ✅ Verified |
| **MI-11** | The MetaIntelligenceTree has no `entity_id` | Any query filtering on `entity_id` finds nothing. The correct filter is `scope_level=TENANT`. Easy to get wrong, and the failure is an empty result rather than an error | 📄 Doc-reported |
| **MI-12** | The README says six tree sections; there are seven | `composition` is missing from the README table | 📄 Doc-reported |
| **MI-13** | `meta_spec_critic` is a `Tool` outside the registry | Instantiated directly, so `ToolRegistry.get_tool` never finds it. Also recorded as [TX-04](09-TOOLS-DEFECTS.md#tx-04--meta_spec_critic-is-a-tool-that-is-not-in-the-registry) | 📄 Doc-reported |
| **MI-14** | Synthesised tools register tenant-scoped and are unreachable | `tool_synthesis_pipeline` registers a `DRAFT` tool with `register_tenant_tool`. The executor never passes `company_id`, so the tool cannot be resolved even in the process that registered it — see [TL-10](TOOL-LAYER-DEFECTS.md#tl-10--tenant-scoped-tools-are-unreachable-by-construction) | ✅ Verified |

---

## 5. T3 — Silent data loss and tuning traps

### MI-15 — Tree sections cap at 200 rows and drop the oldest silently

**📄 Doc-reported · Medium**

Each MetaIntelligenceTree section is LRU-pruned at 200 rows on `last_seen`. Old
anti-patterns, prompt candidates and calibration rules disappear with no record.

For anti-patterns in particular this is the wrong policy: a rare failure mode that has not
recurred in a while is exactly the one worth remembering, and it is the first to be
evicted.

**Fix:** prune on age with a floor on high-confidence rows, or archive rather than delete.

---

### MI-16 — Tool synthesis runs its test harness outside the sandbox

**✅ Verified · Critical**

Recorded in full as
[TL-02](TOOL-LAYER-DEFECTS.md#tl-02--tool-synthesis-executes-generated-code-outside-the-sandbox).
Summarised here because it belongs to this subsystem:

`ToolSandboxTester.run_examples` allocates its harness workdir with
`tempfile.mkdtemp(prefix="toolsynth_")` — bare `/tmp`, not the tenant workspace, and not
bind-mounted into the container. Under `ContainerRuntime` the `cwd` does not exist and the
exec fails.

So **the only configuration in which tool synthesis works is the one where the generated
code runs unsandboxed on the host** — the exact inverse of the stated design.

The capability is off by default (`meta_agent.tool_synthesis_enabled = False`), which is
what keeps this from being live today.

---

### MI-17 — Prompt evolution writes candidates nothing surfaces urgently

**📄 Doc-reported · Low**

`meta_agent_prompt_evolution` runs weekly and writes prompt-update candidates into the
tree. It never auto-applies — an admin must POST the approve endpoint.

That is the correct safety posture. The gap is that nothing notifies anyone that
candidates are waiting, so the queue is only seen by someone who happens to open the
Meta-Intelligence page. A weekly job whose output nobody is told about will accumulate and
then be approved in bulk without review.

---

### MI-18 — The test budget is shared and exhaustion looks like a pass

**📄 Doc-reported · Medium**

The TestDriver suite runs against a shared `$3.00` budget. Exhaustion produces skipped
cases ([MI-05](#mi-05--a-skipped-test-case-is-not-a-failed-one)) rather than an error.

Since the budget is shared across the board's work, one expensive spec earlier in the day
can silently reduce every later spec's test coverage to nothing.

---

### MI-19 — Drift detection compares a hash nothing acts on

**📄 Doc-reported · Low**

The platform schema compiler computes a hash of the compiled capability surface and
detects drift between the compiled "firmware" and the live platform.

Detection exists. There is no automated response — no rebuild, no alert, no gate on
promotion. The drift is recorded and a human must notice.

- [`ai/meta/platform_schema_compiler.py`](../../../backend/src/ai/meta/platform_schema_compiler.py)

---

## 6. Improvements

### MI-I1 — Make the gates fail closed

**Effect: large for safety, small in code.**
[MI-01](#mi-01--the-duplicate-check-fails-open). Three `except` blocks currently turn a
broken check into a permission. Invert them, and emit a metric on gate failure so a
persistently broken gate is visible rather than silently permissive.

### MI-I2 — Move anti-sprawl into the creation service

**Effect: large.** [MI-02](#mi-02--antisprawlguard-advises-and-only-one-caller-listens).
Today one of several creation paths enforces the limits. Moving the check into
`AIService.create_entity` makes it universal and removes the possibility of a new creation
path forgetting.

### MI-I3 — Give the Architect a real rewrite, or drop the loop

**Effect: large on cost and outcome.**
[MI-06](#mi-06--the-architect-cannot-revise-so-the-critic-loop-cannot-converge). Right now
every spec costs three critic calls that cannot change the outcome, and then blocks.

Either wire the Meta-Agent entity in as the rewriter — the docstring anticipates exactly
this — or run one critique and stop. The current shape is the worst of both.

### MI-I4 — Cache the platform schema compilation

**Effect: medium.** `platform_schema_compiler.py` is 898 lines that walk the entire
capability surface — every tool, every schema, every enum — to produce the "firmware" JSON
injected into Meta-Agent prompts.

The result changes only when code changes. Compile at startup and cache with the hash it
already computes, rather than recompiling per request.

### MI-I5 — Score reuse so semantic similarity can matter

**Effect: medium.** [MI-09](#mi-09--semantic-similarity-alone-can-never-trigger-reuse).
Either raise the semantic weight or lower the ADAPT threshold so a strong semantic match
can carry a decision. As configured, the most expensive signal in the scorer is also the
one that can never be decisive.

### MI-I6 — Make skipped tests visible everywhere

**Effect: medium.** [MI-05](#mi-05--a-skipped-test-case-is-not-a-failed-one) and
[MI-18](#mi-18--the-test-budget-is-shared-and-exhaustion-looks-like-a-pass). A suite result
should carry `ran`, `passed`, `failed`, `skipped`. Then G4 is a sanity check rather than
the only thing standing between an untested spec and promotion.

### MI-I7 — Notify when human-gated queues have items

**Effect: medium.** Four things wait for a human: merge proposals, skill candidates,
prompt candidates and DRAFT tool promotions. None of them notifies anyone.

A count on the admin dashboard, or a weekly digest, turns four dormant queues into a
working review process. Without it, the "requires a human" column of the safety table
means "never happens".

### MI-I8 — Prune the tree by age and confidence, not by count

**Effect: medium.** [MI-15](#mi-15--tree-sections-cap-at-200-rows-and-drop-the-oldest-silently).
LRU on `last_seen` evicts exactly the rare-but-important entries. Age plus a floor on
high-confidence rows keeps the useful ones.

### MI-I9 — Rate-limit entity creation within the day

**Effect: small.** [MI-03](#mi-03--the-daily-creation-limit-is-company-wide-with-no-rate-limit).
A per-minute cap alongside the daily one turns a burst into a trickle, which is what you
want from a runaway loop. `ai/governance/rate_limiter.py` is a working sliding-window
limiter with zero call sites — this is a natural first one.

### MI-I10 — Act on schema drift

**Effect: small.** [MI-19](#mi-19--drift-detection-compares-a-hash-nothing-acts-on). The
hash is already computed. Gate promotion on it, or at minimum surface it on the
Meta-Intelligence page. Detection that produces no action is a log line.

---

## 7. Suggested order of work

| Step | Work | Why here |
|---|---|---|
| **1** | MI-10, MI-12 | The `similar_id` key mismatch and the README count. Minutes each, and MI-10 blinds a human reviewer today |
| **2** | MI-I1 / MI-01 | Fail closed. Three `except` blocks |
| **3** | MI-I2 / MI-02 | Move anti-sprawl into the creation service so every path is covered |
| **4** | MI-I3 / MI-06, MI-07 | Fix or drop the revise loop. Either way it stops costing three calls for nothing |
| **5** | MI-I6 / MI-05, MI-18 | Make skipped tests visible before anything is promoted on a suite result |
| **6** | MI-16 | Fix the synthesis harness workdir **before** `meta_agent.tool_synthesis_enabled` is ever turned on |
| **7** | MI-I7, MI-I8 | Make the human queues visible; stop dropping rare anti-patterns |
| **8** | MI-I4, MI-I5 | Cache the schema compile; make the reuse scorer able to use its most expensive signal |

---

## Where to go next

- [11 — Meta-intelligence & the Meta-Agent Board](../11-meta-intelligence.md) — the source
  document.
- [`TOOL-LAYER-DEFECTS.md`](TOOL-LAYER-DEFECTS.md) — TL-02 and TL-10 for MI-14 and MI-16.
- [06 — Execution pipeline](06-EXECUTION-PIPELINE-DEFECTS.md) — the entity shape the Board
  produces and the DRAFT → ACTIVE lifecycle.
- [08 — Memory & CORTEX](08-MEMORY-AND-CORTEX-DEFECTS.md) — the tree substrate the
  MetaIntelligenceTree reuses.
- [15 — Governance & HITL](15-GOVERNANCE-AND-HITL-DEFECTS.md) — the feature flags gating
  this whole layer.
