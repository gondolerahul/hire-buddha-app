# 20. Developer Onboarding & Glossary — Defect Register

> **What this document is:** defects in the onboarding experience itself — the day-one
> setup, the first-change exercise, the mental model a newcomer is given, and the glossary
> — plus the improvements that would shorten time-to-first-commit.
> **Source document:** [`20-onboarding-and-glossary.md`](../20-onboarding-and-glossary.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`.
> **Context:** this is the only document in the set whose defects are measured in **a new
> developer's wasted hours**. Several of them teach an incorrect mental model, which is
> more expensive than a broken command.

---

## How to read this file

- **✅ Verified** — the code, config or doc was read on 2026-09-01 and the claim held.
- **📄 Doc-reported** — from `20-onboarding-and-glossary.md`, not independently re-checked.
- Two kinds of defect live here:
  1. **Setup defects** — the documented path does not produce a working system.
  2. **Model defects** — the document teaches something that is not true of the code.
     These are worse, because the developer carries them into every subsequent ticket.

---

## Contents

1. [Summary](#1-summary)
2. [T0 — The documented setup does not work](#2-t0--the-documented-setup-does-not-work)
3. [T1 — The onboarding teaches the wrong model](#3-t1--the-onboarding-teaches-the-wrong-model)
4. [T2 — Stale references](#4-t2--stale-references)
5. [T3 — Glossary and navigation](#5-t3--glossary-and-navigation)
6. [Improvements](#6-improvements)
7. [Suggested order of work](#7-suggested-order-of-work)

---

## 1. Summary

| Tier | Theme | Count | When to do it |
|---|---|---|---|
| [T0](#2-t0--the-documented-setup-does-not-work) | The documented setup does not work | 4 | **Now** — every new hire hits these |
| [T1](#3-t1--the-onboarding-teaches-the-wrong-model) | The onboarding teaches the wrong model | 5 | Now — cheapest to fix, most expensive to leave |
| [T2](#4-t2--stale-references) | Stale references | 5 | Free |
| [T3](#5-t3--glossary-and-navigation) | Glossary and navigation | 4 | Opportunistically |

**Total: 18 defects, 10 improvements.**

The three to read first:

- **[ON-01](#on-01--the-setup-sequence-omits-two-required-steps)** — follow the documented
  steps exactly and the phone inventory and sandbox SKU are missing.
- **[ON-05](#on-05--section-33-describes-a-memory-block-that-is-never-injected)** — the
  mental model section teaches a feature that does not run.
- **[ON-06](#on-06--the-first-change-exercise-targets-a-deprecated-tool-through-an-unwired-gate)** —
  the guided first task exercises a function nothing calls, on a tool that should be
  deleted.

---

## 2. T0 — The documented setup does not work

### ON-01 — The setup sequence omits two required steps

**✅ Verified · High**

The day-one flow is: install → `.env` → docker → `alembic upgrade head` →
`seed_admin_user.py` → npm → `start_services.sh`.

Two steps are missing, and both are documented elsewhere in the same set
([03 §15](../03-data-model.md)):

| Missing step | Consequence |
|---|---|
| `python -m migrations.merge_phone_tables` | `phone_numbers` is created by **no** Alembic migration. Without it the whole phone inventory is absent — see [DM-02](03-DATA-MODEL-DEFECTS.md#dm-02--phone_numbers-is-created-by-a-script-not-a-migration) |
| `python -m scripts.seed_sandbox_sku` | Without the `sandbox-runtime` SKU, sandbox metering logs a warning and records nothing |

A developer following document 20 exactly gets a database missing a table the ORM
references, and discovers it only when a phone-numbers page 500s.

- [`backend/migrations/merge_phone_tables.py`](../../../backend/migrations/merge_phone_tables.py)
- [`backend/scripts/seed_sandbox_sku.py`](../../../backend/scripts/seed_sandbox_sku.py)

---

### ON-02 — Step 4 is "edit a file to fix a shipped default"

**✅ Verified · High**

The setup diagram has a highlighted step: **"4. EDIT .env — change 5432 to 5433"**, and the
prose calls it "the single most common day-one failure".

Documenting a workaround for a wrong default, and highlighting it in the diagram, is the
wrong fix. `.env.example` should ship with 5433, which is what `docker-compose.yml` maps.

The same wrong default also sits in `UnifiedGatewaySettings.DATABASE_URL`
([SA-03](02-SYSTEM-ARCHITECTURE-DEFECTS.md#sa-03--the-gateways-default-database-port-is-wrong)).

- [`backend/.env.example`](../../../backend/.env.example)
- Also **D-45** in the platform register

---

### ON-03 — The verification step passes on a system that cannot run an agent

**✅ Verified · Medium**

The documented verification is: curl the two health endpoints, import `WorkerSettings`, run
the unit tests, open the browser.

All four pass on a system with **no LLM integration configured** — at which point every
agent run fails with "No model configured"
([LP-10](10-LLM-PROVIDERS-DEFECTS.md#lp-10--nothing-is-seeded-so-a-fresh-install-cannot-run-an-agent)).
`model_task_defaults` starts empty and nothing seeds it.

The troubleshooting table does mention "Agent runs but does nothing → No LLM credentials",
so the knowledge exists — it just is not part of the verification.

---

### ON-04 — The five-process table lists a process nothing starts

**✅ Verified · Medium**

§1 states: *"Five processes on one VM — Backend 8000, Gateway 8001, **Voice 8002**, Arq
worker, Vite 3000."*

`start_services.sh` starts four. Port 8002 is retired, unstarted, and described as such by
the gateway's own code.

The same document contradicts itself at §9 item 9, which correctly says the voice service
is not started. A newcomer reading top to bottom learns the wrong thing first.

- [`start_services.sh`](../../../start_services.sh)
- Same as [SA-01](02-SYSTEM-ARCHITECTURE-DEFECTS.md#sa-01--streaming_host-defaults-to-a-service-that-does-not-run) and **W-1**

---

## 3. T1 — The onboarding teaches the wrong model

### ON-05 — Section 3.3 describes a memory block that is never injected

**✅ Verified · High**

The mental-model section says:

> Four typed memory domains (Knowledge, Episodic, Experience, Intelligence) feed a
> `__memory__` block that gets injected into the prompt.

`assemble_memory` — the function that builds that block — has **zero production callers**.
`AgentLoop` constructs its `Perceiver` with `memory_assembler=None`, and `step_executor`
actively **strips** `__memory__` from child contexts.

So one of the four load-bearing concepts a new developer is told to learn describes
behaviour the platform does not have. Anyone debugging "why doesn't the agent remember?"
will start from a false premise.

- [`ai/memory/assembler.py:19`](../../../backend/src/ai/memory/assembler.py:19) — no callers
- [`ai/core/agent_loop.py:766`](../../../backend/src/ai/core/agent_loop.py:766) — `memory_assembler=None`
- Full write-up:
  [MC-01](08-MEMORY-AND-CORTEX-DEFECTS.md#mc-01--cortex-is-write-only-on-the-live-path)

**Fix:** either wire it (which is a small change and the right one), or change §3.3 to say
memory is currently written and not read.

---

### ON-06 — The first-change exercise targets a deprecated tool through an unwired gate

**✅ Verified · High**

The guided exercise is: enable the `EXPERIMENTAL` `video_generation` tool for your dev
tenant by inserting a `tools.experimental.video_generation` feature-flag row, then assert
that `ToolRegistry.get_visible_tools_for_company` surfaces it.

Three problems:

1. `video_generation` is **`ToolStatus.DEPRECATED`**, not `EXPERIMENTAL`, and is a
   deletion candidate ([PO-17](01-PRODUCT-OVERVIEW-DEFECTS.md#4-t2--dead-code-and-dead-surfaces)).
2. `get_visible_tools_for_company` has **no production callers** — only this test and a
   comment ([TL-13](TOOL-LAYER-DEFECTS.md#tl-13--the-tool-status-gate-is-not-wired-into-execution)).
3. So the exercise's assertion passes while the tool is *already executable* by any entity
   that names it, flag or no flag.

The first thing a new developer is taught is therefore a control that does not control
anything — and they are taught it as though it works.

- [`backend/src/ai/ONBOARDING.md:65`](../../../backend/src/ai/ONBOARDING.md:65)–75
- [`ai/tools/base.py:192`](../../../backend/src/ai/tools/base.py:192) — the unwired gate

---

### ON-07 — "Most gates fail open" is stated and then not acted on

**✅ Verified · Medium · partially good**

§9 item 2 is admirably honest: *"Most gates fail open… A broken gate looks exactly like a
passing gate. Read logs, not just outcomes."*

That is correct and valuable. The gap is that it is presented as a **quirk to work around**
rather than a defect to fix. A newcomer learns to distrust the controls rather than to
report them.

See [GH-21](15-GOVERNANCE-AND-HITL-DEFECTS.md#gh-21--almost-every-gate-in-the-platform-fails-open)
for the full list and
[GH-I2](15-GOVERNANCE-AND-HITL-DEFECTS.md#gh-i2--emit-a-metric-whenever-a-gate-fails-to-evaluate)
for the fix.

---

### ON-08 — The quality gates a newcomer is told to run are not enforced anywhere

**✅ Verified · High**

§8.1 presents the layout lint's rules as things that "will fail your build". §5's exercise
diagram shows a `CI` participant returning green.

There is no CI. The one workflow filters on a directory that no longer exists
([TS-01](19-TESTING-DEFECTS.md#ts-01--the-only-ci-workflow-has-never-fired)). §9 item 7 and
a note in §5 both say so.

So the document tells the newcomer both that the build enforces these rules and that nothing
runs them. The first framing is the one in the diagram.

---

### ON-09 — `core/` has 20 lines of headroom and the doc says so twice

**✅ Verified · Medium**

`agent_loop.py` is ~1,480 lines against a 1,500-line cap, flagged in both §8.1 and the
gotchas.

Telling a new developer "your first change to the control loop must also be a refactor" is
accurate and is a poor first experience. The right response is to extract before the next
contributor arrives, not to document the wall.

- [`backend/scripts/lint_ai_layout.py`](../../../backend/scripts/lint_ai_layout.py)
- Same as [IN-17](18-INFRASTRUCTURE-AND-DEPLOYMENT-DEFECTS.md#in-17--core-is-20-lines-from-its-lint-cap)

---

## 4. T2 — Stale references

| ID | Problem | Notes | Status |
|---|---|---|---|
| **ON-10** | `src/ai/models.py` is a deprecated shim still in the tree | Re-exports every ORM class from `src.ai.orm.*` so old imports keep working. §7.3 lists it as a trap. It has been a trap for long enough — delete it and fix the importers | ✅ Verified |
| **ON-11** | The root `tests/` directory | Four `__init__.py` files and nothing else. §7.3 lists it as a trap. Deleting it removes the trap entirely. Also [TS-09](19-TESTING-DEFECTS.md#4-t2--dead-scaffolding) | ✅ Verified |
| **ON-12** | `backend/cortex_memory_moved_to_pypi_repo/` | The directory name is itself the documentation. §7.3 and §9 item 5 both explain it. Either publish the package or move it back — see [MC-I10](08-MEMORY-AND-CORTEX-DEFECTS.md#mc-i10--decide-where-cortex_memory-lives) | ✅ Verified |
| **ON-13** | `core/README.md` documents two files that do not exist | `execution_engine.py` and `recursive_engine.py`. §7.4 recommends it as worth reading. Also [AK-14](05-AGENT-KERNEL-DEFECTS.md#4-t2--delete-or-fix-the-name) | ✅ Verified |
| **ON-14** | `docs/phase9/` through `docs/phase12/` | Historical plans kept alongside current documentation. §7.4 warns "the code is truth", which is the right instruction and does not stop a newcomer opening them first. Move them under `docs/history/` | 📄 Doc-reported |

---

## 5. T3 — Glossary and navigation

### ON-15 — The glossary lists two deprecated reasoning modes without saying so

**✅ Verified · Low**

> **Reasoning strategy** — REACT, CHAIN_OF_THOUGHT, REFLECTION, TREE_OF_THOUGHTS

`REFLECTION` and `TREE_OF_THOUGHTS` are in `DEPRECATED_REASONING_MODES`. They are still
accepted and emit a deprecation warning, and a data migration
(`p12_retire_reasoning_modes`) already moved existing entities off them.

The glossary presents four equal options where there are two.

- [`ai/schemas/enums.py`](../../../backend/src/ai/schemas/enums.py) — `DEPRECATED_REASONING_MODES`

---

### ON-16 — "42 boolean + 5 numeric flags" is right and unhelpful

**✅ Verified · Low**

The count is exactly correct — `DEFAULTS` has 42 keys and `NUMERIC_DEFAULTS` has 5.

What the number does not convey is that **at least eight of them have no reader**
([GH-16](15-GOVERNANCE-AND-HITL-DEFECTS.md#4-t2--feature-flags-that-are-not-controls)), and
one of those actively contradicts the runtime
([TX-01](09-TOOLS-DEFECTS.md#tx-01--the-per-company-sandbox-flag-is-never-read)).

"42 flags change behaviour at runtime" is the sentence in the document. Roughly 34 do.

---

### ON-17 — The glossary defines terms for features that do not run

**📄 Doc-reported · Low**

`Viewport`, `ScopePolicy` and `Memory domain` are all defined as live concepts. All three
belong to the memory read path, which has no callers
([ON-05](#on-05--section-33-describes-a-memory-block-that-is-never-injected)).

They are correct descriptions of the design. They should be marked as design-not-yet-wired,
the way the document already marks other things honestly.

---

### ON-18 — The "20-minute tour" points at documents whose 60-second sections describe unwired features

**📄 Doc-reported · Low**

The recommended fast path is to read only §1 of documents 01–19. That is good advice, and
those sections are where the aspirational descriptions are densest — memory injection,
credit gating at four points, 98 tools, the visibility gate.

Each of those is corrected later in its own document, in a section the tour skips.

**Fix:** a one-line "known gaps" pointer at the end of every §1, linking to that document's
register in this folder.

---

## 6. Improvements

### ON-I1 — Make setup one script

**Effect: large.** [ON-01](#on-01--the-setup-sequence-omits-two-required-steps),
[ON-02](#on-02--step-4-is-edit-a-file-to-fix-a-shipped-default),
[ON-03](#on-03--the-verification-step-passes-on-a-system-that-cannot-run-an-agent).

A `./bootstrap_dev.sh` that does everything — venv, `.env` with the **right** port, docker,
migrations, `merge_phone_tables`, `seed_admin_user`, `seed_sandbox_sku`, npm, and a seeded
`text_generation` default — replaces ten manual steps and three documented workarounds.

Time-to-first-run goes from "an afternoon and a colleague" to one command.

### ON-I2 — Add a `doctor` command

**Effect: large.** [ON-03](#on-03--the-verification-step-passes-on-a-system-that-cannot-run-an-agent).
One script that checks: database reachable on the right port, migrations at head,
`phone_numbers` exists, admin user exists, `model_task_defaults` has a `text_generation`
row, Redis reachable, worker heartbeat present, and which routers failed to mount
([API-I2](17-API-REFERENCE-DEFECTS.md#api-i2--surface-failed-router-mounts)).

That covers the majority of "it's broken and I don't know why" for both new developers and
on-call.

### ON-I3 — Replace the first-change exercise

**Effect: medium, and it sets the tone.**
[ON-06](#on-06--the-first-change-exercise-targets-a-deprecated-tool-through-an-unwired-gate).
The current exercise teaches an unwired gate on a deprecated tool.

Better first tasks, each real and small: add the missing `DELETE /ai/documents/{id}`
([PO-01](01-PRODUCT-OVERVIEW-DEFECTS.md#po-01--deleting-a-knowledge-base-document-always-fails)),
register the two missing worker jobs
([MC-I3](08-MEMORY-AND-CORTEX-DEFECTS.md#mc-i3--register-the-two-missing-worker-jobs)), or
add the four missing indexes
([DM-I1](03-DATA-MODEL-DEFECTS.md#dm-i1--add-the-indexes-the-queries-already-assume)).

Each teaches a real part of the system and leaves the codebase better.

### ON-I4 — Mark the unwired parts of the mental model

**Effect: large for correctness of understanding.**
[ON-05](#on-05--section-33-describes-a-memory-block-that-is-never-injected),
[ON-17](#on-17--the-glossary-defines-terms-for-features-that-do-not-run).

The document is already unusually honest in §9 and §7.3. Extending that honesty into §3
— the mental model — is the highest-value edit in this file. A newcomer who knows memory is
write-only today will debug correctly; one who does not will lose a day.

### ON-I5 — Link every document to its register

**Effect: medium.** [ON-18](#on-18--the-20-minute-tour-points-at-documents-whose-60-second-sections-describe-unwired-features).
One line at the end of each §1: *"Known defects and improvements:
[NN-...-DEFECTS.md](...)"*. The tour then produces an accurate picture instead of an
aspirational one.

### ON-I6 — Delete the three traps in §7.3

**Effect: medium.** [ON-10](#4-t2--stale-references), [ON-11](#4-t2--stale-references),
[ON-12](#4-t2--stale-references). §7.3 is titled "Where the code is *not*" and lists three
places a newcomer will look and not find things.

Two of the three can simply be deleted — the `models.py` shim and the root `tests/`
directory. That is better than documenting them.

### ON-I7 — Extract from `agent_loop.py` now

**Effect: medium.** [ON-09](#on-09--core-has-20-lines-of-headroom-and-the-doc-says-so-twice).
Twenty lines of headroom means the next contributor to the kernel is forced into a
refactor they did not plan. Doing the extraction deliberately, now, is cheaper than doing
it under a ticket.

### ON-I8 — Move the phase docs to `docs/history/`

**Effect: small.** [ON-14](#4-t2--stale-references). Four directories of historical plans
sit beside current documentation. Relocating them makes "the code is truth" a directory
structure rather than a warning.

### ON-I9 — Add a "how to verify your change actually runs" section

**Effect: large for this codebase specifically.** The most common defect shape across all
twenty registers is a module that is complete, unit-tested, and **never called**. A new
developer can write a well-tested feature here and ship nothing.

One short section — grep for call sites outside tests, add a trace span, run it end to end
and see it in the trace viewer — would inoculate against the single most common failure in
this repository. Pairs with
[TS-I7](19-TESTING-DEFECTS.md#ts-i7--add-a-declared-but-never-called-check).

### ON-I10 — Keep one accurate process/port table

**Effect: small.** [ON-04](#on-04--the-five-process-table-lists-a-process-nothing-starts).
The five-process table appears in documents 01, 02, 18 and 20, and they do not all agree
about port 8002. One table, referenced from the others.

---

## 7. Suggested order of work

| Step | Work | Why here |
|---|---|---|
| **1** | ON-02, ON-01 | Fix `.env.example`, then fold the two missing steps into the setup |
| **2** | ON-I1 — one bootstrap script | Replaces the whole day-one section with a command |
| **3** | ON-I4 / ON-05, ON-17 | Correct the mental model. The most expensive defect to leave in place |
| **4** | ON-I6 / ON-10, ON-11, ON-13 | Delete the two traps and fix the stale README |
| **5** | ON-I3 / ON-06 | Replace the first-change exercise with a real, useful task |
| **6** | ON-I2 — the doctor command | Serves new developers and on-call equally |
| **7** | ON-I5, ON-I9 | Link the registers; teach how to verify a change runs |
| **8** | ON-I7 / ON-09 | Extract from `agent_loop.py` before the next contributor hits the cap |

---

## Where to go next

- [20 — Developer onboarding & glossary](../20-onboarding-and-glossary.md) — the source
  document.
- [`README.md`](../README.md) — the documentation index this register set sits under.
- [`DEFECT-REGISTER.md`](../DEFECT-REGISTER.md) — the platform-wide list.
- [18 — Infrastructure](18-INFRASTRUCTURE-AND-DEPLOYMENT-DEFECTS.md) — the full setup and
  operations picture behind ON-01 to ON-03.
- [08 — Memory & CORTEX](08-MEMORY-AND-CORTEX-DEFECTS.md) — MC-01, the defect behind
  ON-05.
- [19 — Testing](19-TESTING-DEFECTS.md) — TS-I7, the check that would catch the
  "never called" pattern ON-I9 warns about.
