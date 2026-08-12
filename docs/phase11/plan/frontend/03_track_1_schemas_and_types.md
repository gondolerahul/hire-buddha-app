# Frontend Track 1 — Schemas & Types (parallel with backend T1)

> **Backend Track:** [`../03_track_1_schemas_and_orm.md`](../03_track_1_schemas_and_orm.md)
> **Owner:** App platform / frontend engineer.
> **Duration:** 2 working days.
> **Behaviour change:** None visible to users. Types tightened.
> **Risk:** Low — pure refactor with type checks.

---

## 1. Objectives (functional)

After Frontend Track 1:

1. `frontend/src/types/index.ts` (432 lines) is split into a `types/`
   package mirroring the backend `schemas/` split.
2. Every typed enum from
   [`01_overview_and_principles.md` §3.1](./01_overview_and_principles.md)
   exists in `types/enums.ts`.
3. A lightweight **codegen pipeline** generates `types/_generated.ts`
   from a snapshot of `backend/src/ai/schemas/*.py` so frontend stays
   in sync. Initial impl is manual/scripted; full OpenAPI codegen is
   deferred to Phase 12.
4. `PlanStep.type`, `HITLCheckpoint.trigger_type`, and other newly-
   strict backend enums are reflected as TS enums on the frontend.
5. `FailureTag` enum exists in `types/enums.ts` for downstream Tracks.

---

## 2. Scope

### In scope

* Split `types/index.ts` into per-domain files.
* Add new enums and dataclasses listed in §3.
* Add a one-off Python script that generates a TypeScript skeleton
  from the backend Pydantic models (best-effort; safe to regenerate).
* Update all `import` statements inside `frontend/src/` to use the new
  paths (codemod).
* `types/index.ts` becomes a wildcard re-export shim for back-compat.

### Out of scope

* Full OpenAPI/JSON-schema-driven codegen (Phase 12).
* Removing the legacy `index.ts` re-exports (Track 9-FE will do this if
  ever justified).
* Any UI change.

---

## 3. Architecture (technical)

```
frontend/src/types/
├── index.ts               ← back-compat wildcard re-export (existing path)
├── enums.ts               ← NEW (closed enums)
├── entity.ts              ← NEW (HierarchicalEntity*, Hierarchy*)
├── execution.ts           ← NEW (ExecutionRun*, LLMInteractionLog, ToolInteractionLog, HumanApproval)
├── planning.ts            ← NEW (PlanStep, PlanStepTarget, StaticPlan, DynamicPlanning, ExitCondition)
├── reasoning.ts           ← NEW (LogicGate, ReasoningConfig, RetryPolicy, ReviewMechanism, ContextPolicy)
├── capabilities.ts        ← NEW (Capabilities, MemoryConfig, MetaCognitionConfig, ContextEngineering, ContextSource, ToolReference, ToolAuth, ToolDefinition)
├── governance.ts          ← NEW (Governance, HITLCheckpoint, ExecutionLimits)
├── io_contract.ts         ← NEW (IOContract, Observability)
├── cortex.ts              ← NEW (CortexTree, CortexNode, GoalNode, Viewport)
├── document.ts            ← NEW (Document, DocumentChunk types)
├── tools.ts               ← NEW (ToolRegistryEntry*, ToolStatus)
├── agent_state.ts         ← NEW (T-FE-2 reuses; here we just declare it)
├── critic.ts              ← NEW (StepHealthRecord, verdicts)
├── meta.ts                ← NEW (Meta-Agent payloads; populated more in T-FE-5)
├── memory.ts              ← NEW (Provenance, IntelRule, BanditArm)
├── plan.ts                ← NEW (PlanCandidate, PlanCandidates, PlanInvariant)
├── kpi.ts                 ← NEW (KPI rollup row shapes)
├── feature_flags.ts       ← NEW (FeatureFlag, FeatureFlagValue)
└── _generated.ts          ← codegen-output (read-only header marker)
```

Existing `types/index.ts` keeps every export available via:

```ts
// types/index.ts (after Track 1)
export * from './enums';
export * from './entity';
export * from './execution';
export * from './planning';
export * from './reasoning';
export * from './capabilities';
export * from './governance';
export * from './io_contract';
export * from './cortex';
export * from './document';
export * from './tools';
export * from './agent_state';
export * from './critic';
export * from './meta';
export * from './memory';
export * from './plan';
export * from './kpi';
export * from './feature_flags';
```

---

## 4. Detailed deliverables

### 4.1 FE-T1-1 — Create the new files (Day 1 AM)

For each new file in §3 picture, create the module with the matching
types from the backend Phase-11 plan, plus the existing exports moved
from `index.ts`.

**Rule:** every Pydantic model in `backend/src/ai/schemas/` has a
corresponding TS interface with the SAME name (e.g.
`HierarchicalEntityCreate` → `HierarchicalEntityCreate`).

**Naming caveats:**

* Python's `Optional[X]` → TS `X | null` for fields that are nullable
  on the JSON, or `X | undefined` (`?: X`) when the field is omitted.
* Python's `Decimal` → TS `string` (we never use `number` for money).
* Python `UUID` → TS `string` (UUIDs are strings on the wire).
* Python `datetime` → TS `string` (ISO-8601).

### 4.2 FE-T1-2 — Wildcard re-export from `index.ts` (Day 1 PM)

Convert `types/index.ts` to a barrel file. Any duplicate name (e.g. if
two modules both export `Persona`) is a hard error — track owner picks
one canonical home.

```bash
# verify no duplicates:
cd frontend
npx tsc --noEmit
```

If TS reports a name collision, resolve by moving to one canonical
module + a `// re-exported from ...` comment in the other.

### 4.3 FE-T1-3 — Codegen script (Day 2 AM)

Write `backend/scripts/codegen_frontend_types.py`. It reads the
Pydantic schemas in `backend/src/ai/schemas/` and emits a single
`frontend/src/types/_generated.ts` with:

* Every `str-Enum` as a TS `enum`.
* Every Pydantic model as a TS `interface`.
* A header: `// AUTO-GENERATED. Do not edit by hand. Run scripts/codegen_frontend_types.py.`

```python
# backend/scripts/codegen_frontend_types.py
#!/usr/bin/env python
"""
Best-effort Pydantic→TypeScript skeleton generator.

Reads backend/src/ai/schemas/*.py, emits frontend/src/types/_generated.ts.

Limitations:
  - JSONB-typed fields → 'Record<string, unknown>'
  - Discriminated unions → flat union (loses tag)
  - Validators are not converted (UI-side validation lives in zod schemas)

Used as a *skeleton* — the per-domain handwritten files (entity.ts,
planning.ts, ...) take precedence and may add UI-only convenience fields.

Usage: cd backend && .venv/bin/python scripts/codegen_frontend_types.py
"""
...
```

The generated file is NOT imported anywhere — it's a **reference**
checked into the repo. CI diffs the regenerated output against the
committed file and fails if they differ (so any backend schema change
forces an intentional update of the codegen output).

### 4.4 FE-T1-4 — Codemod imports inside `frontend/src/` (Day 2 PM)

The wildcard re-export keeps every old import working. As a
*follow-up* polish, optionally codemod existing imports to deep
imports for IDE / tree-shaking benefits:

```bash
# Optional — codemod can stay deferred to Track 9-FE.
npx jscodeshift -t scripts/codemod_types_imports.ts frontend/src/
```

For Track 1 the minimum bar is **back-compat works**; deep-import
codemod is bonus.

### 4.5 FE-T1-5 — Zod schemas for new forms

Every form that lets a user set a typed enum value gets a zod schema
referencing the TS enum. For Track 1 the only existing form that
strictly needs this is `EntityBuilder`:

```ts
// pages/ai/EntityBuilder.tsx (Track-1 addition)
import { z } from 'zod';
import { StepType, ReasoningMode, EntityType } from '@/types';

const planStepSchema = z.object({
  step_id: z.string().optional(),
  order: z.number().int(),
  name: z.string().min(1),
  description: z.string().optional(),
  type: z.nativeEnum(StepType),       // ← TYPED now, not z.string()
  target: z.object({
    entity_id: z.string().uuid().optional(),
    tool_id: z.string().optional(),
    prompt_template: z.string().optional(),
    input_dependencies: z.array(z.string()).default([]),
  }).optional(),
  required: z.boolean().default(true),
});
```

If `EntityBuilder` previously accepted `type: z.string()`, the new
schema forces a valid `StepType` — UX surfaces a dropdown, not free
text.

---

## 5. Database / schema changes

N/A.

---

## 6. API changes

N/A. The wire format is identical.

> Caveat: if the EntityBuilder previously accepted a free-text
> `type: ""` for a new step, the new zod schema rejects it. Existing
> drafts (in localStorage) saved with an empty `type` get coerced to
> `StepType.ACTION` on load via a one-off migration in the EntityBuilder
> draft-loader.

---

## 7. Telemetry events

N/A.

---

## 8. Feature flags

N/A — pure refactor. Flag-gated UI changes start in T-FE-2.

---

## 9. Tests

### 9.1 Unit

* `test_types_back_compat` — A TS test file imports every symbol that
  was previously exported from `types/index.ts` and asserts the import
  resolves. (`tsc --noEmit` is sufficient; a `// @ts-expect-error` line
  per absent symbol would fail compilation.)
* `test_step_type_zod_coercion` — `planStepSchema.parse({type: 'tool_call'})`
  succeeds (the zod `nativeEnum` is case-sensitive — confirm
  uppercase form is required, since backend now enforces it).
* `test_failure_tag_enum_complete` — assert `Object.values(FailureTag).length === 12`.

### 9.2 Build

* `npm run build` passes.
* CI step: run the codegen and `git diff --exit-code
  frontend/src/types/_generated.ts` (catches forgetting to regenerate).

### 9.3 Manual smoke

* Open EntityBuilder; create a new step; confirm the `type` dropdown
  has all StepType values; save; reload; verify the saved type.
* Open ExecutionDetail for an existing run; confirm it renders as
  before (no regression).

---

## 10. Acceptance criteria

1. `frontend/src/types/` is a directory with the files listed in §3.
2. `import { ... } from '@/types'` works for every symbol previously
   exported.
3. `FailureTag`, `ExecutorName`, `CriticVerdictKind`,
   `SupervisorRecommendation`, `RetryStrategy`, `ToolStatus`,
   `CostAttribution`, `MetaBoardRole` enums exist in `types/enums.ts`.
4. `_generated.ts` is checked in and CI fails on drift.
5. `npm run build` clean; `npm run lint` clean.
6. EntityBuilder forces valid `StepType` via zod.

---

## 11. Effort (2 days)

| Day | Work |
|-----|------|
| 1 AM | FE-T1-1: split files; add new enums |
| 1 PM | FE-T1-2: barrel re-export; resolve any duplicates |
| 2 AM | FE-T1-3: codegen script + checked-in output |
| 2 PM | FE-T1-4 (optional codemod) + FE-T1-5 zod schemas |

---

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Pydantic→TS skeleton misses fields | M | Frontend silently sends nulls | Per-domain handwritten files take precedence; codegen is reference-only |
| Two modules export the same name | L | Build error | TS catches at compile time |
| Existing EntityBuilder drafts had `type: ""` | L | Draft load fails validation | One-off migration in draft loader |
| zod runtime errors on previously-permissive payloads | M | EntityBuilder save fails | Pre-Track 1, run codepath against fixture entities; gate via a tiny try/catch with friendly error |

---

## 13. Dependencies

* **Upstream:** Backend T1 (so the codegen has stable input).
* **Downstream:** Every later FE Track imports from `@/types`.

---

## 14. Open questions

* Should `_generated.ts` be the **primary** source and handwritten
  files just additions, or is it strictly reference? **Decision:**
  reference. Phase 12 may flip this once we have OpenAPI codegen.
* Where do **UI-only types** live (e.g. `IterationCard` derived
  state)? Per-page co-located unless they're shared by ≥3 pages, in
  which case `types/ui.ts`.
