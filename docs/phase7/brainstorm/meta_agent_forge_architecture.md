# Meta-Agent FORGE — A Novel Architecture for Flawless Entity Generation

**Status:** Greenfield architectural proposal. Independent of any existing Meta-Agent V1/V2/V3 design. Treat as a clean-room reset.

**One-line thesis:** Stop asking an LLM to write `HierarchicalEntity` JSON. Ask it to write a *specification* in a tiny typed language, then derive the entity from the specification through a deterministic compiler, prove the entity satisfies the specification, and ship only entities that come with a machine-checkable certificate.

---

## 0. Why "Flawless" Is Defensible

"Flawless" is a strong word. I am not claiming an LLM will never err. I am claiming an architecture where **LLM errors cannot reach the registry undetected** — because every entity that ships carries a constructive proof against a spec the user signed.

The trick is not better prompting. The trick is **moving the LLM out of the position where its errors are unrecoverable**. In every prevailing meta-agent design (including the existing HireBuddha V2), the LLM directly produces the deliverable, and validation is a post-hoc filter. Filters miss things. FORGE inverts this: the LLM produces a *specification*, and the deliverable is *derived and verified* against that specification. Whole categories of failure (wrong tool name, malformed JSON, broken `{{var}}` reference, infeasible governance budget, unreachable step, hallucinated enum value) are eliminated by **construction**, not detected after the fact.

This is the difference between a typed compiler with a sound type system and a linter you run on dynamic-language source. Linters catch bugs probabilistically. Type systems eliminate them constructively. FORGE is a type system for agent generation.

---

## 1. The Seven Commitments

These are non-negotiable design axioms. Every other choice in FORGE follows from them.

1. **The LLM never writes the deliverable.** It writes specifications and proposes synthesis steps under formal constraints. Final entity JSON is *emitted* by deterministic code.
2. **Every entity ships with a Certificate.** No certificate, no registry insertion. The certificate is mechanically reproducible from `(IntentSpec, CapabilityProgram, EntitySchema, TestEvidence)`.
3. **Generation is constructive synthesis under refutation, not autoregressive sampling.** The synthesizer proposes; the verifier refutes with a counterexample; the synthesizer repairs. This is Counterexample-Guided Inductive Synthesis (CEGIS), adapted to agent payloads.
4. **Reuse is logical subsumption, not vector similarity.** An existing entity reuses if its capability formally covers the new specification. No magic thresholds.
5. **The spec is the source of truth.** All downstream artifacts derive from it. Spec changes propagate; entities derived from a stale spec are auto-flagged invalid.
6. **All side effects are fenced.** Synthesis runs in a fully-stubbed sandbox. Property tests run in a stubbed sandbox. Real execution is a separate, authorized, and auditable step.
7. **The whole pipeline is a pure function of `(NL prompt, registry snapshot, platform manifest, RNG seed)`.** Replayable. Auditable. Falsifiable.

If any of these break, the "flawless" claim collapses.

---

## 2. Architecture at a Glance

```
                   ┌─────────────────────┐
   NL request ───► │  S1. Intent Capture │ ◄── User confirms IntentSpec
                   │  (grammar-constrained LLM dialog)
                   └──────────┬──────────┘
                              │ IntentSpec (typed)
                              ▼
                   ┌─────────────────────┐
                   │ S2. Spec Derivation │ ◄── No LLM. Pure compiler.
                   │ (IntentSpec → CapabilityProgram)
                   └──────────┬──────────┘
                              │ CapabilityProgram (typed IR)
                              ▼
            ┌──────────────────────────────────┐
            │ S3. Reuse Subsumption Check      │
            │ (SMT solver over typed contracts)│
            └────┬───────────────────┬─────────┘
                 │ subsumes          │ partial fit
                 │ (REUSE)           │ (ADAPT/COMPOSE)
                 │                   │ no fit (CREATE)
                 ▼                   ▼
   ┌──────────────────┐  ┌──────────────────────────┐
   │ Wrap with        │  │ S4. Entity Synthesis     │
   │ adapter SKILL    │  │ (CEGIS loop)             │
   │ if needed        │  │  Proposer (LLM, grammar-constrained)
   └─────────┬────────┘  │  Verifier (deterministic)
             │           │  Refiner  (counterexample → patch)
             │           └────────────┬─────────────┘
             │                        │ EntitySchema (typed)
             ▼                        ▼
            ┌─────────────────────────────────┐
            │ S5. Certification               │
            │ (property tests in sandbox)     │
            └────────────┬────────────────────┘
                         │ all properties pass
                         ▼
                ┌────────────────────┐
                │ Certificate Issued │
                └─────────┬──────────┘
                          ▼
                  Registry insertion
                  + immutable audit record
```

Five stages. Stages 2, 3, and 5 are deterministic. Stages 1 and 4 use LLMs but under hard structural constraints (grammar-constrained decoding) and verified outputs.

---

## 3. The Specification Language: `IntentSpec`

The first hard problem is capturing user intent in a form that is **expressive enough** for real agents but **constrained enough** to enable downstream determinism. FORGE introduces a tiny typed DSL: `IntentSpec`.

### 3.1 Grammar (EBNF)

```ebnf
IntentSpec     = Goal Inputs Outputs Capabilities Invariants Budget Triggers
Goal           = "goal" ":" QuotedString
Inputs         = "inputs" ":" "[" InputDecl ("," InputDecl)* "]"
InputDecl      = Name ":" Type ("=" Default)? ("where" Predicate)?
Outputs        = "outputs" ":" "[" OutputDecl ("," OutputDecl)* "]"
OutputDecl     = Name ":" Type ("ensures" Predicate)?
Capabilities   = "capabilities" ":" "{" CapabilityClass+ "}"
CapabilityClass= ("read"|"write"|"compute"|"egress"|"deliberate") ":" CapabilityRef+
CapabilityRef  = ToolFamily ("(" Constraint ")")?    (* by family, not by tool name *)
Invariants     = "invariants" ":" Predicate*
Budget         = "budget" ":" "{" "cost_usd" ":" Float "," "wall_ms" ":" Int
                                  ("," "llm_calls" ":" Int)? "}"
Triggers       = "triggers" ":" TriggerDecl*
TriggerDecl    = "manual" | "schedule" "(" CronExpr ")" | "webhook" "(" Url ")"
                | "child_of" "(" EntityRef ")"
Predicate      = (* small first-order logic over Inputs/Outputs *)
Type           = "string" | "int" | "float" | "bool" | "uuid" | "json"
                | "list" "<" Type ">" | "record" "{" FieldDecl+ "}"
```

### 3.2 Worked example

```yaml
goal: "Find SaaS companies that raised Series B in the last N days
       and email a CSV of decision-makers to the requester."
inputs:
  - industry: string  where industry in ["SaaS","FinTech","HealthTech"]
  - days_back: int    where days_back > 0 and days_back <= 365  = 90
  - recipient: string where matches_email(recipient)
outputs:
  - csv_path: string  ensures exists(csv_path) and ends_with(csv_path, ".csv")
  - row_count: int    ensures row_count >= 0 and row_count <= 5000
capabilities:
  read:    [WebSearch, ProspectDatabase(provider in ["Apollo","ZoomInfo"])]
  compute: [Summarize, Filter, Dedupe]
  write:   [FileWriter(format="csv")]
  egress:  [EmailSend(to=recipient)]   (* parameterized by input *)
invariants:
  - never(egress before write)         (* causally ordered *)
  - egress.recipient == inputs.recipient
  - row_count <= 5000                  (* matches output ensures *)
budget:
  cost_usd: 0.50
  wall_ms:  120000
  llm_calls: 8
triggers:
  - manual
  - schedule("0 9 * * MON")            (* every Monday 9am *)
```

### 3.3 Why this DSL works

- **Capability families, not tool names.** The user (or LLM that helps draft the spec) commits to "I need an email egress capability", not "I need `email_send`". Tool resolution happens in S2, against the live registry. The spec survives tool renames, swaps, and additions.
- **Predicates are first-order, decidable.** `where`, `ensures`, and `invariants` are restricted to a fragment that an SMT solver (Z3) can decide. No quantifier alternation over uninterpreted functions.
- **Causal invariants** (`never(egress before write)`) are temporal predicates over the planned execution graph — not the LLM transcript. This catches data-exfiltration patterns and ordering bugs at spec time.
- **Budgets are constraints, not hopes.** Synthesis must produce an entity whose worst-case cost provably stays under `cost_usd`. Provability comes from per-tool cost models (see §6.3).

### 3.4 How the LLM produces an IntentSpec safely

LLM output is **grammar-constrained at the token level** (this is supported by every modern inference stack: Anthropic's tool use with `input_schema`, OpenAI's structured outputs, llama.cpp's GBNF, vLLM's `outlines`). The LLM literally cannot emit a token sequence that violates the EBNF. A separate type-checker pass rejects spec drafts where predicates reference undeclared variables, or where types are inconsistent.

Failure mode: LLM produces a syntactically valid but semantically wrong spec ("the user said email but I wrote sms"). Mitigation: stage S1 ends with a **back-translation** — render the IntentSpec as English bullet points, present it to the user, require explicit confirmation. The user signs the spec, not the entity. This is the only mandatory HITL in FORGE.

---

## 4. The Capability IR: `CapabilityProgram`

S2 takes an `IntentSpec` and emits a `CapabilityProgram` — a typed dataflow graph in static-single-assignment form. This is the IR that all downstream stages reason about. **No LLM is involved in S2.**

### 4.1 Shape

```
CapabilityProgram = {
  ports_in  : [TypedPort],
  ports_out : [TypedPort],
  nodes     : [Node],          # SSA-form operations
  edges     : [DataEdge],      # producer port → consumer port
  controls  : [ControlEdge],   # ordering invariants from spec
  budgets   : ResourceBudget,
  triggers  : [Trigger],
  predicates: {pre, post, inv} # carried from IntentSpec, normalized
}

Node = OneOf<
  ReadOp(family, output_type, cost_model),
  ComputeOp(family, input_types, output_type, cost_model),
  WriteOp(family, input_type, side_effect, cost_model),
  EgressOp(family, payload_type, side_effect, cost_model),
  ChoiceOp(predicate, branches: [SubGraph]),     # conditional
  IterateOp(over: edge, body: SubGraph),         # bounded loop
  CallEntityOp(entity_ref, input_map, output_map)# reuse existing
>
```

### 4.2 Compilation rules (sketch)

The compiler is a deterministic recursive descent over the IntentSpec, with capability-class lookup:

```
compile(IntentSpec) → CapabilityProgram | TypedError

  Π = port_decls(IntentSpec.inputs, IntentSpec.outputs)
  G = empty_graph(Π)

  for each capability_class in IntentSpec.capabilities:
      for each capability_ref in class:
          node = lower_capability(capability_ref, current_types(G))
          G.add_node(node)

  G = wire_dataflow(G, predicates(IntentSpec))   # SMT-driven edge inference
  G = inject_control_edges(G, IntentSpec.invariants)
  G = check_well_typed(G)                        # rejects type-incoherent graphs
  G = check_budget_feasibility(G, IntentSpec.budget) # cost model bounds

  return G or TypedError(reason, blame_location)
```

### 4.3 What S2 catches

- Capability families with no implementation in the registry (`ProspectDatabase` family is empty for this tenant) → typed error, surfaces back to S1 for spec revision.
- Type mismatches between produced and consumed values (e.g., a tool family produces `list<record>` but the spec's output expects `string`) → typed error with the exact node and edge.
- Causal invariant violations (e.g., the natural lowering would put egress before write) → typed error.
- Worst-case budget overrun under cost model → typed error with the offending node.

S2 is the pivotal stage. Every error caught here is an error that *cannot* reach an LLM, an SMT solver, or a sandbox — it's an error caught by a 1ms compile.

---

## 5. Reuse via Subsumption (S3)

V2-style "vector similarity" reuse is statistical guessing. FORGE replaces it with **logical subsumption**. The subsumption check answers a sharp question: *does an existing entity's CapabilityProgram cover the new spec's CapabilityProgram?*

### 5.1 Definition

Existing entity `E` (with `CapabilityProgram E.P`) **subsumes** the new requirement `R.P` iff:

1. **Input compatibility:** `R.P.inputs ⊆ E.P.inputs` (modulo provided defaults), and the type of each shared port in `R.P` is a subtype of the corresponding port in `E.P`.
2. **Output compatibility:** `E.P.outputs ⊇ R.P.outputs`, and each required output type in `R.P` is a subtype of `E.P`'s.
3. **Predicate implication:** `E.P.post ⇒ R.P.post` and `R.P.pre ⇒ E.P.pre`. (Z3 decides these in milliseconds for the predicate fragment we allow.)
4. **Capability containment:** every capability family used by `R.P` appears in `E.P` with at least the constraints `R.P` requires.
5. **Invariant preservation:** every causal invariant in `R.P` is implied by `E.P`'s control edges.
6. **Budget envelope:** `E.P`'s worst-case cost ≤ `R.P.budget.cost_usd`.

Each clause is a deterministic check. The conjunction is the subsumption verdict.

### 5.2 Three outcomes, three artifacts

| Verdict | Condition | Artifact |
|---|---|---|
| **REUSE** | All clauses hold | `entity_ref` + identity-adapter (no-op) |
| **ADAPT** | Clauses 1, 4, 5, 6 hold; 2 or 3 partial | `entity_ref` + **derived adapter SKILL** (S4 generates the adapter, not the whole agent) |
| **COMPOSE** | No single `E` subsumes; covering set `{E1, E2, ...}` does (set-cover over capability classes) | New PROCESS that calls existing entities; S4 generates only the orchestration |
| **CREATE** | No covering set exists | Full S4 synthesis |

### 5.3 Why this is dramatically better than similarity scoring

- **No magic thresholds.** Subsumption is binary per clause; the verdict is a conjunction.
- **No popularity bias.** A 1-day-old entity that subsumes wins over a 6-month-old that doesn't.
- **No false positives.** If subsumption holds, the existing entity is provably (modulo cost model accuracy) sufficient.
- **No false negatives** at the family level — capability containment uses the live registry's family-to-tool mapping.
- **Adapters are derived, not designed.** When clauses 2 or 3 partially hold, the *delta* between specs becomes the input to a constrained adapter synthesis. The adapter is a SKILL with at most ~3 steps; CEGIS synthesizes it deterministically in seconds.

### 5.4 Set-cover for COMPOSE

When no single entity subsumes, FORGE runs a small set-cover ILP (integer linear program — entity registries are O(thousands), not O(millions); this terminates in <100ms):

> Find the minimum-cardinality set of entities whose union of capability families covers `R.P.capabilities`, and whose composition (per the dataflow in `R.P`) preserves all invariants.

If a feasible cover exists, COMPOSE. Otherwise CREATE. ILP gives you optimality guarantees and a witness — the chosen entities — that becomes the children of the new PROCESS.

---

## 6. CEGIS Synthesis (S4)

When CREATE is required, FORGE runs **counterexample-guided inductive synthesis**: a tight loop between an LLM-based proposer and a deterministic verifier. The LLM is fenced; the verifier is the source of truth.

### 6.1 The loop

```
synthesize(CapabilityProgram P, IntentSpec I) → EntitySchema | UnsatReport

  history = []                      # accumulated counterexamples
  budget_remaining = synthesis_budget(I)

  while budget_remaining > 0:
      proposal = propose(P, I, history)         # LLM call, grammar-constrained
      verdict  = verify(proposal, P, I)         # deterministic, total

      if verdict.ok:
          return proposal                       # passes static verification

      history.append(verdict.counterexample)    # structured failure object
      budget_remaining -= 1

  return UnsatReport(reason, history, partial_proposals)
```

### 6.2 The proposer

The proposer LLM is given:
- The `CapabilityProgram` (its target IR).
- The `IntentSpec` (English-readable).
- The grammar of `HierarchicalEntity` JSON, including all enum values from the live manifest.
- The history of counterexamples from prior loop iterations.

Output is constrained to valid `HierarchicalEntity` JSON via grammar-constrained decoding. **Tool names are restricted at the token level** to the families `CapabilityProgram` resolved. Step types, reasoning modes, HITL trigger types, and every other enum are restricted at the token level. The LLM cannot emit a syntactically invalid entity. It can still emit semantically wrong entities — that's what verify() catches.

### 6.3 The verifier

The verifier is a battery of deterministic checks; each produces either `ok` or a structured `Counterexample` with a `blame_location` and a `repair_hint`:

| Check | What it catches | Counterexample form |
|---|---|---|
| Schema typecheck | Pydantic model errors | `{path, expected_type, got}` |
| Tool signature match | Wrong arg shape to a tool | `{step_id, tool, expected_args, got_args}` |
| Variable resolution | `{{foo}}` references a non-existent name | `{step_id, ref, scope}` |
| Dataflow soundness | Step consumes an output never produced | `{step_id, missing_input, suggested_producer}` |
| Cost-model bound | Worst-case cost exceeds `IntentSpec.budget` | `{exceeds_by, bottleneck_step}` |
| Causal invariant | Some execution order violates `never(...)` | `{invariant, witnessing_path}` |
| Recursion safety | Transitive descendant equals the meta-agent | `{cycle_path}` |
| Egress safety | Read-then-egress without checkpoint | `{read_step, egress_step, missing_hitl}` |
| Reachability | Step is unreachable from any trigger | `{step_id}` |
| Termination | Bounded-loop body has no decreasing measure | `{loop_step, suggested_measure}` |

These checks run on the entity's **structural form**. They do not execute the entity, do not make LLM calls, and run in ~tens of milliseconds total.

### 6.4 Why CEGIS is the right pattern here

Pure single-shot LLM generation has unbounded failure modes. Pure constraint-solving doesn't scale to entities with rich semantics. CEGIS combines them: the LLM proposes a candidate plausibly satisfying *all* constraints; the verifier finds the most local refutation; the LLM patches just that refutation. Empirically (in program synthesis literature) this converges in 2–5 iterations for problems of this complexity.

### 6.5 Budget exhaustion

If the loop exhausts its budget without finding a verifying proposal, `UnsatReport` is emitted. **Critical:** an `UnsatReport` is *not* a failure to be hidden. It's a falsifiable assertion that this `CapabilityProgram` cannot be satisfied within the budget by the current proposer. The report includes:
- All counterexamples encountered (frequency, recurrence patterns).
- The tightest budget extension that the closest proposal would need.
- A minimal repro: the IntentSpec, manifest hash, registry snapshot, RNG seed.

This goes to a human reviewer. The pipeline does not silently degrade.

---

## 7. Certification (S5)

Static verification (S4) catches structural errors. Certification catches *behavioral* errors. The gate is property-based testing in a sandboxed worker.

### 7.1 Property generation

From `IntentSpec`, the certifier auto-generates a test suite:

1. **Boundary inputs.** For each input port, enumerate boundaries (min, max, just-inside-`where`, just-outside-`where`). Hypothesis-style strategies derived from the predicates.
2. **Adversarial inputs.** For each `where` predicate, generate inputs satisfying the predicate but pathological (empty strings, max-length strings, Unicode edge cases, boundary integers).
3. **Postcondition checks.** Each `ensures` clause becomes a runtime assertion executed on the entity's output.
4. **Invariant checks.** Each `invariants` clause becomes an execution-trace assertion verified against the worker's step log.
5. **Budget checks.** Each test asserts `cost_usd ≤ IntentSpec.budget.cost_usd × 1.1` (10% slack for cost-model imprecision).

Property count target: 25–100 per entity. Synthesis is deterministic from the spec, so the same spec always produces the same suite (good: no flaky tests).

### 7.2 The sandbox

A dedicated execution mode in the worker:
- LLM calls go to a real but cheap model (haiku-class) with `max_tokens` capped at 200.
- Tool calls are dispatched to **stub implementations** registered per tool family. Stubs are *contract-faithful* — they return data of the declared output shape, with values drawn from a fixed corpus (so behavior is deterministic across runs). Stubs record every call for trace assertions.
- All writes (DB, file, queue) go to in-memory mocks scoped to the test run.
- Any attempt at real egress (email, slack, HTTP) is intercepted and recorded as an assertion target, never executed.

This is non-trivial infrastructure (~2 weeks of work) but it pays for itself the first week it's in production.

### 7.3 The Certificate

A passing entity emits a Certificate — a signed, content-addressed record:

```yaml
certificate:
  certificate_id:    sha256(intent_hash || program_hash || schema_hash || evidence_hash)
  issued_at:         2026-05-10T14:22:01Z
  issuer:            forge.v1
  intent_spec_hash:  ab12cd34...
  program_hash:      ef56...
  schema_hash:       7890...
  manifest_hash:     12ab...        # platform manifest at certification time
  registry_hash:     34cd...        # registry snapshot used for subsumption
  rng_seed:          0x7f3a...      # for replayability
  evidence:
    properties_total:    63
    properties_passed:   63
    properties_failed:   0
    sandbox_runs:        63
    cost_observed:       $0.31      # vs $0.50 budget
    wall_ms_observed:    87413      # vs 120000 budget
    llm_calls_observed:  6          # vs 8 budget
    detailed_trace_uri:  s3://forge-evidence/certificates/{certificate_id}/trace.json.zst
  signature:           ed25519:...
```

### 7.4 Decoupling certification from delivery

Critical design choice: the certificate is **not** "the entity passed tests." It is a *witness package* that any third party (auditor, second meta-agent, future you) can independently re-verify by:
1. Loading the spec, program, schema, manifest, registry from their hashes.
2. Re-running the property suite against the spec.
3. Hashing the new evidence and comparing to the certificate.

If the recheck fails, the certificate is voided and the entity is suspended in the registry with a "stale certificate" status. This is how FORGE handles platform drift: an entity whose certificate becomes invalid (because its manifest hash changed) does not silently degrade — it explicitly fails recertification.

---

## 8. The Trust Model

I claimed "flawless." Let me be precise about what that means.

**FORGE provides:**
- A guarantee that no entity reaches the registry without passing all structural checks of S4 (deterministic).
- A guarantee that no entity reaches the registry without passing all spec-derived properties of S5 (sandboxed, deterministic per seed).
- A guarantee that the certificate is reproducible from `(spec, program, manifest, registry, seed)`.
- A guarantee that any entity in the registry can be **re-certified** at any time, and entities whose recertification fails are automatically marked suspended.
- A guarantee that the user signed an English-readable rendering of the IntentSpec, so the gap between user intent and machine spec is bounded by the back-translation quality (which is itself testable).

**FORGE does NOT provide:**
- A guarantee that the IntentSpec captures what the user *meant* (NL ambiguity is unsolvable).
- A guarantee that the cost model exactly predicts production cost (it's a model; budget tests use 10% slack).
- A guarantee that a tool's stubbed contract matches its real-world behavior — though contract tests in CI keep these aligned (see §11).
- A guarantee that the SMT solver always terminates on adversarial predicates (the predicate fragment is restricted; pathological inputs are rejected at parse time, not run time).

The honest claim is: **FORGE eliminates entire classes of failure that plague autoregressive entity generation, and makes the remaining classes auditable and recoverable.** That is what "flawless" means in this design.

---

## 9. End-to-End Worked Example

Same user request as §I in the V3 brainstorm: *"Find SaaS companies that raised Series B in the last 90 days and email me a CSV of decision-makers."*

```
S1. INTENT CAPTURE
  LLM dialog (3 turns, grammar-constrained):
    Turn 1: extract goal, inputs, outputs from NL
    Turn 2: ask clarifying question — "should existing leads in your CRM be deduped?"
            User: "yes"
    Turn 3: emit candidate IntentSpec (the YAML in §3.2 above)
  Back-translation rendered as English bullets.
  User: confirms. IntentSpec is signed with user_id + timestamp.

S2. SPEC DERIVATION
  Compiler walks the spec; lowers each capability class:
    - WebSearch         → resolves to {web_search} family in manifest
    - ProspectDatabase  → resolves to {apollo_search, zoominfo_search}; tenant has Apollo
    - Summarize         → llm-action node (no tool)
    - Filter, Dedupe    → llm-action nodes
    - FileWriter(csv)   → resolves to {file_writer} with format constraint
    - EmailSend(to=recipient) → resolves to {email_send}; binds recipient port
  Emits CapabilityProgram with 7 nodes and a control edge enforcing
  invariant: write completes before egress.
  Worst-case cost computed from per-node cost models: $0.41 (under $0.50 budget) ✓
  Time: 4ms.

S3. SUBSUMPTION
  Iterate registry candidates; for each, run 6-clause check.
  Candidate "lead-research-skill v1.4": clauses 1, 2, 4, 5, 6 hold; clause 3 partial
    (its `post` does not entail the new "row_count <= 5000" output ensures).
  Verdict: ADAPT.
  Adapter spec: a 1-step SKILL that asserts row_count post-condition and truncates if needed.

S4. ENTITY SYNTHESIS (only the adapter)
  Iter 1: Proposer emits a 1-step SKILL.
          Verifier: ✗ — adapter's input port name doesn't match
          lead-research-skill's output ("rows" vs "leads").
          Counterexample: {step_id: 1, missing_input: "leads", suggested_producer: "lead-research-skill.outputs.leads"}
  Iter 2: Proposer fixes the binding.
          Verifier: ✓
  Iterations: 2. Time: 3.1s. LLM cost: $0.008.

S5. CERTIFICATION
  Certifier generates 47 properties from the IntentSpec.
  Sandbox runs:
    - 12 boundary tests (industry values, days_back min/max, recipient formats)
    - 18 adversarial tests (long industries, invalid emails, days_back=365)
    - 17 invariant tests (write-before-egress, recipient binding, row_count cap)
  All 47 pass. Observed cost in sandbox: $0.29. Wall: 71s. LLM calls: 5.
  Certificate emitted, signed, persisted to evidence store.

DELIVERY
  PROCESS entity created in registry: "hn-saas-series-b-emailer" wrapping
  lead-research-skill v1.4 + new adapter SKILL.
  metadata_extensions includes: certificate_id, intent_spec_hash, decision=ADAPT.
  Audit log entry written.
  User shown: contract card + "Run now" button.

TOTAL pipeline cost: $0.012 (1 LLM dialog + adapter synthesis + sandbox)
TOTAL wall time:     11s (mostly sandbox runs in parallel)
```

Compare to V2: same user request, no certificate, direct LLM-generated entity, post-hoc validation, no formal subsumption, no property tests. FORGE costs ~5× more in pipeline LLM tokens but eliminates ~all failure modes.

---

## 10. What "Flawless Hierarchical Entities" Looks Like in the Database

After delivery, the row in `hierarchical_entities` looks like every other row — same 8 JSON columns, same FK relationships. FORGE makes **two additions**:

```sql
ALTER TABLE hierarchical_entities ADD COLUMN certificate_id UUID REFERENCES forge_certificates(id);
ALTER TABLE hierarchical_entities ADD COLUMN intent_spec_id UUID REFERENCES forge_intent_specs(id);

CREATE TABLE forge_intent_specs (
  id UUID PRIMARY KEY,
  spec_yaml TEXT NOT NULL,
  spec_hash CHAR(64) NOT NULL UNIQUE,
  user_id UUID NOT NULL,            -- who signed it
  signed_at TIMESTAMPTZ NOT NULL,
  back_translation TEXT NOT NULL    -- exactly what the user saw and approved
);

CREATE TABLE forge_certificates (
  id UUID PRIMARY KEY,
  certificate_id_content_addr CHAR(64) NOT NULL UNIQUE,
  intent_spec_hash CHAR(64) NOT NULL,
  program_hash CHAR(64) NOT NULL,
  schema_hash CHAR(64) NOT NULL,
  manifest_hash CHAR(64) NOT NULL,
  registry_hash CHAR(64) NOT NULL,
  rng_seed BYTEA NOT NULL,
  evidence_uri TEXT NOT NULL,
  signature BYTEA NOT NULL,
  status TEXT NOT NULL DEFAULT 'valid',  -- valid | suspended | voided
  issued_at TIMESTAMPTZ NOT NULL,
  recertified_at TIMESTAMPTZ
);
```

The runtime worker (`worker.py`) is **modified in exactly one place**: at run-start, it reads `entity.certificate_id`. If null, it refuses to execute (legacy entities can be exempted via a flag during migration). If non-null, it checks `forge_certificates.status`. If `suspended`, it pauses the run and surfaces a recertification prompt. If `valid`, execution proceeds normally.

This is the only worker change. Everything else FORGE does is upstream of the worker.

---

## 11. Implementation Modules (concrete, mappable to a sprint plan)

| Module | Path (suggested) | LOC est. | Owner |
|---|---|---|---|
| IntentSpec parser + grammar | `backend/src/ai/forge/intent/grammar.py` | ~400 | new |
| Predicate type-checker | `backend/src/ai/forge/intent/predicates.py` | ~600 | new (uses Z3) |
| Back-translation renderer | `backend/src/ai/forge/intent/render.py` | ~200 | new |
| CapabilityProgram IR | `backend/src/ai/forge/ir/program.py` | ~500 | new |
| Compilation passes | `backend/src/ai/forge/ir/compile.py` | ~800 | new |
| Cost model registry | `backend/src/ai/forge/ir/cost_models.py` | ~300 | new |
| Subsumption engine | `backend/src/ai/forge/reuse/subsumption.py` | ~700 | new (uses Z3) |
| Set-cover ILP | `backend/src/ai/forge/reuse/cover.py` | ~250 | new (PuLP or OR-tools) |
| Adapter synthesis | `backend/src/ai/forge/synth/adapter.py` | ~400 | new |
| CEGIS proposer | `backend/src/ai/forge/synth/proposer.py` | ~500 | new |
| Verifier suite | `backend/src/ai/forge/synth/verifier.py` | ~1000 | new |
| Property generator | `backend/src/ai/forge/cert/properties.py` | ~600 | new (Hypothesis) |
| Sandbox worker | `backend/src/ai/forge/cert/sandbox.py` | ~800 | extends `worker.py` |
| Certificate signer/verifier | `backend/src/ai/forge/cert/certificate.py` | ~300 | new |
| Pipeline orchestrator | `backend/src/ai/forge/pipeline.py` | ~400 | new |
| Migration | `backend/alembic/versions/xxxx_forge.py` | ~100 | DB change |
| Tool stubs (per family) | `backend/src/ai/forge/stubs/*.py` | ~150 × N tools | per-tool author |
| Tool contract tests | `backend/tests/contract/*.py` | ~100 × N tools | per-tool author |
| Frontend pipeline UI | `frontend/src/pages/forge/*.tsx` | ~2000 | UI |

**Total backend Python:** ~7.7K LOC core + tool stubs (which are tiny). At a senior engineer's pace, the core is a 10–14 week build. The frontend UI is parallel work.

The boundary that matters: **the existing platform code (worker, registry, models) is unchanged except for the certificate check at run-start**. FORGE is additive.

---

## 12. Comparative Position vs Prevailing Patterns

| Property | V2 today | LangGraph-style synthesis | OpenAI Assistants | FORGE |
|---|---|---|---|---|
| LLM writes deliverable | Yes | Yes | Yes | **No** |
| Reuse decision | Vector similarity | None | None | **Logical subsumption** |
| Validation | Pydantic + post-hoc | Runtime errors | Runtime errors | **Constructive verification + property tests** |
| Failure recoverability | Rerun | Rerun | Rerun | **Counterexample-guided repair** |
| Audit reproducibility | Partial logs | None | None | **Cryptographic certificate** |
| Behavioral drift handling | Manual annotation | None | None | **Auto-recertification on manifest hash change** |
| Worst-case cost guarantee | None | None | None | **Provable from cost model** |
| Adversarial sprawl resistance | Pairwise dedup | None | None | **Subsumption + cluster ILP** |

This is not "V2 with more LLM calls." It is a categorically different production model.

---

## 13. The Honest Caveats

1. **Cost models for tools.** FORGE depends on per-tool cost models for budget proofs. Building 50 of them is real work and they need calibration over time. Without cost models, budget guarantees degrade to budget heuristics.
2. **Predicate language must stay restricted.** Once users (or the LLM) start needing universal quantifiers over uninterpreted functions, Z3 becomes a liability. FORGE pushes back on those features rather than weakening determinism.
3. **Sandbox stubs are a maintenance burden.** Every new tool requires a stub. Solution: codegen the stub from the tool's declared input/output schema, refine by hand only when behavior matters.
4. **Latency.** FORGE adds ~10–30s of pipeline time before delivery. For interactive use this is fine (user is reading the contract card); for "build this agent in 2 seconds and run it" use cases it is too slow. Acceptable tradeoff for a production-trust system.
5. **First-run cold start.** With an empty registry, every entity is CREATE; subsumption gives no value. FORGE's payoff curves with registry size.
6. **Spec-vs-intent gap.** This gap is irreducible — natural language is ambiguous. FORGE bounds it by mandatory back-translation confirmation. It does not eliminate it.
7. **It is hard to build.** This is not a sprint. It is a quarter of disciplined engineering. The proposal stands or falls on whether "flawless entities" is worth that investment.

---

## 14. Bottom Line

V2 is a faster, cheaper way to produce mostly-correct entities. FORGE is a slower, more expensive way to produce **provably-correct entities, with audit trails that survive subpoena**. Choose based on which failure mode hurts more in your business: shipping fast-but-wrong agents that surprise users, or slow-but-right agents that ship later.

For a platform whose value proposition is "trust us to run agents on your behalf with your customer data" — and HireBuddha's voice/CRM/email integrations make this exactly that platform — FORGE is the right architecture. The compute cost of the pipeline is dwarfed by the cost of one wrongly-generated agent that emails the wrong people the wrong file.

**Build FORGE.** Or don't, and accept that "flawless" was never on offer.
