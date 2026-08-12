# CORTEX — Evaluation Plan

> A concrete benchmarking program for the CORTEX memory system.
> Audience: an engineer who will execute these experiments and report results.
> Scope: 8 experiments grouped into 4 evaluation pillars. Estimated total cost ~$2–4k in API spend and ~4 engineering weeks.

---

## 0. Evaluation Philosophy

We are evaluating a **systems contribution**, not a model contribution. The model stays fixed; only the memory layer varies. Every experiment must satisfy four discipline rules:

1. **Single-variable comparison.** Same LLM, same temperature, same task, same prompt template. Only the memory layer differs.
2. **Identical input/output contract.** All systems answer in the same format so grading is automatic.
3. **Cost-accounted.** Token in / token out / wall-clock / dollars logged per trial.
4. **Statistical rigor.** ≥ 3 independent runs per condition with different random seeds (or temperature ≥ 0.3 with explicit seeds); report mean, std, and 95% CI; significance via paired bootstrap or Wilcoxon signed-rank.

If any of these slips, the result is not publishable.

---

## 1. The Four Pillars and Eight Experiments

| Pillar | Experiment | What it proves |
|---|---|---|
| **A. Long-horizon recall** | E1 — LongMemEval | CORTEX retrieves facts across many sessions as well as or better than Mem0/Letta/Zep |
| | E2 — LoCoMo | CORTEX preserves multi-turn conversational coherence |
| **B. Bounded context property** | E3 — Token-cost scaling | Per-step prompt cost is O(M + depth), decoupled from tree size |
| | E4 — Context rot inoculation | Quality is stable as tree grows; baselines (full-context stuffing) degrade |
| **C. Learning loop (Dreaming)** | E5 — Rule distillation quality | Distilled rules are coherent, non-duplicate, and actionable |
| | E6 — Downstream lift from consolidation | An agent armed with prior-week rules outperforms the same agent without |
| **D. Production properties** | E7 — Sub-agent isolation (formal/fuzz) | RECURSE children cannot mutate parent state |
| | E8 — Resumption correctness | Suspend/resume produces identical final state vs uninterrupted runs |

---

## 2. Experiment A1 (E1) — LongMemEval Head-to-Head

### Hypothesis
*CORTEX achieves equal or higher fact-recall accuracy than Mem0, Letta, and Zep on LongMemEval, while consuming fewer or equal tokens per query.*

### Setup

- **Dataset.** LongMemEval ([Mem0's benchmark](https://github.com/mem0ai/longmemeval), ~500 multi-session conversations with planted factual queries across 5 categories: single-session-user, single-session-assistant, multi-session, knowledge-update, temporal-reasoning).
- **Model.** Fix one LLM across all systems — recommended `gpt-4o-mini` (cheap, well-supported by every framework). Repeat the experiment with `claude-haiku-4-5` to demonstrate model-agnosticism.
- **Embedding model.** Fix `text-embedding-3-small` for *every* system (override CORTEX default, override Mem0 default).
- **Random seeds.** Three runs per (system, model) cell with `seed ∈ {7, 42, 1337}`.

### Baselines

| System | Configuration |
|---|---|
| **None (cold)** | Raw LLM, fresh context each query |
| **Stuff-it** | All prior conversation in context (oracle upper bound on tokens) |
| **Vector RAG** | pgvector over chunked conversation history, top-5 retrieval |
| **Mem0** | `mem0.Memory()` with default settings |
| **Letta (MemGPT)** | Default core/archival/recall tiers |
| **Zep** | Cloud or self-hosted; default settings |
| **CORTEX (this work)** | v2 pipeline, `memory_scope=FULL`, all four domains active |

### Metrics

- **Primary:** F1 on extracted answer string against gold (LongMemEval's official grader).
- **Secondary:** mean prompt tokens per query; mean total tokens per session ingestion; median latency.
- **Tertiary:** $ per 100 queries.

### Expected output shape

```
Table 1. LongMemEval results (gpt-4o-mini, 3 seeds, mean ± std).
                       F1         Tokens/query    $/100q     Latency(p50)
None (cold)          0.21 ± 0.02      ~250          $0.05      0.6s
Stuff-it             0.78 ± 0.03      ~28,000       $5.40      3.1s
Vector RAG           0.62 ± 0.04      ~1,200        $0.24      1.1s
Mem0                 0.68 ± 0.05      ~800          $0.16      1.4s
Letta                0.71 ± 0.04      ~1,100        $0.22      2.2s
Zep                  0.73 ± 0.03      ~900          $0.18      1.6s
CORTEX               <result>         <result>      <result>   <result>
```

### Pitfalls

- Mem0 and Letta both have hosted APIs. Decide upfront: hosted or self-hosted, and apply consistently. Hosted variants benefit from continuous model improvements.
- LongMemEval's grader is LLM-based; pin the grader model to `gpt-4o` and document this.
- Each session's ingestion phase is a write workload, not a query workload. Log both separately.

### Estimated cost
~$200–300 in LLM spend. ~2 engineering days to wire all six baselines + grader.

---

## 3. Experiment A2 (E2) — LoCoMo Multi-Turn Coherence

### Hypothesis
*CORTEX maintains stronger multi-turn coherence than Mem0/Letta/Zep on LoCoMo, particularly on "knowledge update" and "temporal reasoning" categories.*

### Setup

- **Dataset.** [LoCoMo](https://huggingface.co/datasets/snap-research/locomo) (Snap Research): 10 long-form conversations with timestamped events; queries probe whether the agent remembers what was said *and when*.
- **Same baselines, models, seeds as E1.**

### Metrics

- **Primary:** Category-stratified accuracy (single-hop / multi-hop / temporal / open-ended). Report all five categories; do not aggregate them.
- **Coherence sub-metric:** F1 on temporal-reasoning queries specifically. This is where CORTEX's `episode_group` (month/day) hierarchy should shine.
- **Hallucination rate:** % queries where the answer contains a fact not present in any conversation turn (LLM-judged).

### Why this matters separately from E1

LongMemEval is fact-extraction-shaped. LoCoMo is coherence-shaped. They probe different failure modes. A system can win E1 and lose E2 (Mem0's pattern, historically) or vice versa.

### Estimated cost
~$150 spend, ~1 day to run after E1's harness exists.

---

## 4. Experiment B1 (E3) — Token-Cost Scaling Curve

### Hypothesis
*Per-step prompt token cost in CORTEX is bounded by `O(M + depth(cursor))` and is empirically constant as tree size grows from 10 to 100,000 nodes. Baseline "stuff-it" agents grow linearly until they hit the context window ceiling.*

This is the central design claim from §5.3 of the paper. It must be measured precisely.

### Setup

- **Synthetic tree-growth harness.** Generate a sequence of `write()` operations that build trees of size N ∈ {10, 100, 1k, 10k, 100k} nodes. For each tree size, drive the agent through K = 20 steps and log the prompt-token count of each step.
- **Use the same model across all baselines** for tokenization consistency.
- **Vary `max_children`** ∈ {6, 12, 24} to confirm the M dependency.
- **Vary cursor depth** ∈ {2, 5, 10, 15} to confirm the depth dependency.

### Baselines

- **CORTEX viewport mode** (the proposed system).
- **Stuff-it** (concatenate all prior step outputs into the prompt).
- **Rolling window** (last 10 step outputs).
- **Vector RAG** (top-5 from a vector store of all step outputs).

### Metrics

- Mean and 95th percentile prompt tokens per step, by N.
- Mean and 95th percentile completion tokens per step, by N.
- Total $ per 20-step task, by N.

### Expected output shape

A log-log plot of *prompt tokens per step* vs *tree size*. Stuff-it should grow as O(N) up to the model's context limit (then crash); CORTEX should be a horizontal line; vector RAG should be roughly horizontal but with higher absolute cost than CORTEX.

```
Plot 1. Per-step prompt tokens vs tree size (log-log).

  Stuff-it:        ━━━━━╱
  Vector RAG:      ─────────────
  Rolling window:  ─────────────
  CORTEX viewport: ─────────────  ← should overlap rolling window but
                                    with richer content (summaries of
                                    children vs raw text)
```

### Why this experiment is essential

This is the only experiment that proves the *system-level* property of CORTEX, not just task accuracy. Without it, the bounded-context claim in the paper is unsupported.

### Estimated cost
Synthetic — embeddings and a handful of LLM calls per cell. ~$50 total. ~1 day.

---

## 5. Experiment B2 (E4) — Context Rot Inoculation

### Hypothesis
*As task complexity grows, "stuff-it" baselines degrade in accuracy (the context-rot phenomenon Anthropic documents). CORTEX, by keeping the prompt bounded, does not degrade.*

### Setup

- **Synthetic needle-in-haystack tasks.** Plant a known fact ("the secret code is XQ7-998") at varying positions in a long execution history, then ask the agent to retrieve it.
- **History length** ∈ {1, 10, 50, 100, 500} prior step outputs.
- **Needle position** ∈ {start, middle, end, random}.
- **Three repetitions per cell.**

### Baselines

Same as E3.

### Metrics

- **Primary:** Exact-match recall accuracy.
- **Secondary:** Mean cosine similarity between answer embedding and gold embedding (for soft recall).

### Expected output shape

```
Plot 2. Recall accuracy vs history length.

100%  ▲  ●●●●●●●●●●●●●●●●●●●●●●●●  CORTEX
      │
 75%  │  ●─●─●─●─●─●─●          
      │                ●─●       Stuff-it (degrades past ~50 steps)
 50%  │
      │                   ●─●─●  Rolling window (loses old facts)
 25%  │
      │
  0%  ┼──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──→
       1   10   50  100  500
         (history length)
```

### Estimated cost
~$100 spend. ~1 day.

---

## 6. Experiment C1 (E5) — Dreaming Rule Quality

### Hypothesis
*Rules distilled by the Dreaming Engine are (a) coherent, (b) non-duplicate, and (c) actionable — measured by human and LLM-judge ratings.*

### Setup

- **Generate 200 synthetic execution runs** spanning two failure modes (e.g., scraper-blocked-by-cloudflare; tool-empty-on-vague-query) and two success modes (e.g., headless-browser-on-protected-sites; specific-multi-keyword-queries).
- **Run the Dreaming Engine** with default thresholds.
- **Collect the output rules.**

### Metrics

| Metric | Method |
|---|---|
| **Coherence** | LLM-as-judge (Claude-Opus); 5-point Likert rating |
| **Non-duplication** | Pairwise cosine similarity across rules; %pairs > 0.9 |
| **Actionability** | LLM-judge: "Could a junior engineer follow this rule to change behavior?" 5-point |
| **Coverage** | % of seeded failure modes captured in extracted rules |
| **Spurious rule rate** | % rules judged "vague or unfounded" by a panel of 2 humans + 1 LLM judge |

### Ablations

- Disable the confidence filter (`OBSERVATION_CONFIDENCE_THRESHOLD = 0`) → measure increase in spurious rules.
- Disable the de-dup hint in the distillation prompt → measure increase in pairwise-similar rules.
- Vary cluster threshold (0.65, 0.75, 0.85) → measure effect on pattern recurrence count and rule actionability.

### Estimated cost
~$30 in dreaming LLM calls + ~$50 in judging. ~1 day to set up, ~half-day to grade.

---

## 7. Experiment C2 (E6) — Downstream Lift from Consolidation

### Hypothesis
*An agent with Intelligence rules injected outperforms the same agent without — on tasks for which the rules are applicable.*

This is the *ultimate* test of whether Dreaming is doing useful work. If E6 doesn't show lift, E5's rule-quality scores are cosmetic.

### Setup

- **Phase 1 (training).** Run 100 tasks of type T on a fresh entity. Let Dreaming consolidate.
- **Phase 2 (testing).** Run 50 new tasks of type T:
  - **Condition A:** Memory scope = `INTELLIGENCE_ONLY` (rules injected, no episodic noise).
  - **Condition B:** Memory scope = `NONE` (no memory at all; fresh agent).
  - **Condition C:** Memory scope = `FULL` (everything).
  - **Condition D:** Failure-pattern injection only (the `FailurePatternService` heuristic baseline).
- **3 seeds per condition.**

### Task domains (pick two)

| Domain | Why it's a good fit |
|---|---|
| Web research with mixed tools | Failure patterns (cloudflare/captcha) are real and easy to generate |
| SQL generation against a schema | Schema-specific instructions ("always join orders ON customer_id") are well-formed Intelligence rules |
| Customer support triage | Preferences ("always confirm phone number before issuing refund") map cleanly to PREFERENCE nodes |

### Metrics

- **Task success rate** (binary or graded; depends on domain).
- **First-attempt success rate** (no retries / replanning).
- **Mean tokens per task.**
- **Mean retries per task** (proxy for how often the agent dead-ends).

### Expected output shape

```
Table 2. Downstream task success after 100 training tasks (mean ± 95% CI).

Condition                          Success%    1st-try%    Tokens/task    Retries/task
A: INTELLIGENCE_ONLY              0.87 ± .04   0.74 ± .05      4,200         0.4
B: NONE (cold)                    0.61 ± .06   0.42 ± .07      6,800         1.8
C: FULL                           0.85 ± .04   0.71 ± .05      5,900         0.5
D: Failure-pattern heuristic      0.69 ± .05   0.55 ± .06      4,800         1.1

Improvement of A over B (cold):    +0.26 absolute  (paired bootstrap p < 0.001)
Improvement of A over D (heuristic): +0.18 absolute (p < 0.01)
```

### What "success" looks like

- A and C are close. (Intelligence is the active ingredient; episodic noise in C doesn't help much.)
- A meaningfully beats D. (Otherwise the Dreaming Engine is just an expensive version of the keyword-classifier `FailurePatternService`.)
- Tokens/task drop in A vs B because rules let the agent skip dead-end branches.

If A ≈ B, **Dreaming is not earning its keep** and the consolidation pipeline needs redesign.

### Estimated cost
~$200 in training tasks + $200 in test runs = ~$400. ~3 days.

This is **the single most important experiment** in the program. Budget time for it.

---

## 8. Experiment D1 (E7) — Sub-Agent Isolation Correctness

### Hypothesis
*A child execution constructed with `scoped_subtree_root_id = s` cannot read or write any node outside the subtree rooted at `s`.*

This is Property 2 from the paper. It's a correctness claim, not a performance claim, so the experiment is *fuzz testing*, not benchmarking.

### Setup

- **Build a tree** of depth 6 and branching factor 4 (~1,365 nodes).
- **Spawn a child** scoped to a randomly chosen interior node `s`.
- **Generate 10,000 random operation sequences** (mixes of NAVIGATE, READ, WRITE) against the child router, with node IDs drawn from:
  - 50% inside subtree(s)
  - 50% outside subtree(s)

### Metrics

- **Soundness:** % of out-of-scope operations correctly rejected. Must be 100%.
- **Completeness:** % of in-scope operations correctly accepted. Must be 100%.
- **Performance:** mean and p99 latency of the recursive-CTE ancestry check.

### Expected output

```
Table 3. Sub-agent isolation fuzz test (10,000 ops).

Out-of-scope ops rejected: 5,031 / 5,031     (100.00%)
In-scope ops accepted:     4,969 / 4,969     (100.00%)
Ancestry check p50:        0.4 ms
Ancestry check p99:        2.1 ms
```

If soundness < 100%, the system has a security bug. If completeness < 100%, a usability bug.

### Estimated cost
Pure DB work, no LLM. ~$0. ~1 day.

---

## 9. Experiment D2 (E8) — Resumption Correctness

### Hypothesis
*A run interrupted at step k and resumed produces the same final state as an uninterrupted run with identical inputs and seed.*

### Setup

- **Pick a deterministic 20-step task** (e.g., a SQL generation task with `temperature=0` and `seed` set).
- **Baseline run.** Execute the task to completion. Capture: final output, tree node IDs, edge IDs, episodic node ID, total cost, total tokens.
- **Interrupted runs.** For each `k ∈ {5, 10, 15}`:
  - Execute steps 1..k.
  - SIGTERM the worker.
  - Mark the run `SUSPENDED`.
  - Resume via `cortex_resume_scheduled` or explicit `resume_execution`.
  - Capture the same artifacts after resumption.
- **20 trials per k.**

### Metrics

| Metric | Pass condition |
|---|---|
| **Output equality** | resumed.final_output == baseline.final_output (string compare) |
| **Node-set equality** | resumed.node_ids == baseline.node_ids (set compare) |
| **Episode written once** | exactly 1 episodic node per top-level run |
| **No duplicate work** | resumed.cost_usd ≤ baseline.cost_usd + ε (no re-runs of completed steps) |
| **Idempotence** | Resuming a completed run a second time is a no-op |

### Expected output

```
Table 4. Resumption correctness (60 trials).

Interruption point k:           5         10        15
Output equality:                20/20     20/20     20/20
Node-set equality:              20/20     20/20     20/20
Single episode:                 20/20     20/20     20/20
Cost overhead vs baseline:      +2.3%     +1.8%     +0.9%
Idempotent re-resume:           20/20     20/20     20/20
```

### Estimated cost
~$60. ~2 days (the harder part is the SIGTERM-then-resume orchestration).

---

## 10. Cross-Cutting Ablations

These run alongside the main experiments. Each is a single-variable toggle.

| Ablation | Variable | Experiments affected |
|---|---|---|
| **No graph expansion** | `graph_expansion_depth = 0` in `semantic_graph_search` | E1, E2 |
| **No Intelligence** | `memory_scope = "KNOWLEDGE_ONLY"` | E6 |
| **No Experience** | Skip Phase 2 of Dreaming | E5, E6 |
| **No re-clustering** | `max_children = ∞` | E3 (tree shape; not perf) |
| **No co-access edges** | Disable `track_co_access` | E1, E2 |
| **v1 vs v2 retrieval** | `memory_pipeline = "v1"` vs `"v2"` | E1, E2 |
| **Embedding model** | `text-embedding-3-small` vs `text-embedding-005` vs `nomic-embed-text-v1.5` | E1 |

Each ablation answers a specific question: *does this feature pay for itself?* If the answer is "no" for any feature, that's a paper-worthy negative result.

---

## 11. Infrastructure & Tooling

### Required services

```yaml
PostgreSQL 15+ with pgvector
Redis 7+
arq worker
A test harness that can run 7 memory systems behind one API
```

### Recommended tooling

- **Promptfoo** or **LangSmith** for experiment tracking. Both capture token counts, latency, and outputs per trial automatically. **Promptfoo is recommended** — it's open-source, has a clean YAML config, and supports A/B between systems out of the box.
- **DVC** or **MLflow** for tracking which dataset+code commit produced which result.
- **pytest-benchmark** for E3 (token cost scaling) and E7 (latency).
- **Custom grader harness.** A small wrapper around the LLM-as-judge that pins the grader model, retries on timeout, and stores raw judge outputs for audit.

### Repository layout

```
benchmarks/
├── README.md
├── requirements.txt
├── conftest.py
├── adapters/                          # One adapter per memory system
│   ├── base.py                        # MemoryAdapter Protocol
│   ├── cortex_adapter.py
│   ├── mem0_adapter.py
│   ├── letta_adapter.py
│   ├── zep_adapter.py
│   ├── vector_rag_adapter.py
│   ├── stuff_it_adapter.py
│   └── none_adapter.py
├── datasets/
│   ├── longmemeval/                   # Loaded via load_dataset
│   ├── locomo/
│   └── synthetic/
├── experiments/
│   ├── e1_longmemeval.py
│   ├── e2_locomo.py
│   ├── e3_token_scaling.py
│   ├── e4_context_rot.py
│   ├── e5_rule_quality.py
│   ├── e6_downstream_lift.py
│   ├── e7_isolation_fuzz.py
│   └── e8_resumption.py
├── graders/
│   ├── llm_judge.py
│   └── exact_match.py
└── results/
    ├── 2026-06-01_e1_gpt4o-mini/
    │   ├── raw_outputs.jsonl
    │   ├── grader_decisions.jsonl
    │   ├── results.csv
    │   ├── plots/
    │   └── manifest.yaml             # code commit, dataset version, seeds, model
    └── ...
```

### Adapter contract

Every memory system implements the same interface so experiments swap them like LEGO:

```python
class MemoryAdapter(Protocol):
    name: str
    async def reset(self) -> None: ...                          # wipe state
    async def ingest(self, session_id: str, turns: list) -> None: ...
    async def query(self, session_id: str, prompt: str) -> QueryResult: ...
    # QueryResult includes: answer, prompt_tokens, completion_tokens,
    # latency_ms, cost_usd, retrieved_context (for audit)
```

This is non-negotiable. Without it you'll write per-system experiment code and the comparisons won't be apples-to-apples.

---

## 12. Statistical Methodology

- **Seeds.** Three per condition, drawn from `{7, 42, 1337}` for reproducibility.
- **Significance tests.**
  - Paired tasks: Wilcoxon signed-rank.
  - Independent tasks: Mann-Whitney U.
  - For both, report Cliff's delta or rank-biserial as effect size.
- **Confidence intervals.** Bootstrap (10,000 resamples) for any non-Gaussian metric (accuracy, F1).
- **Multiple comparisons.** Bonferroni-correct when comparing >2 systems on the same metric.
- **Reporting.** Always report mean ± std AND mean ± 95% CI. Never just one.
- **Pre-registration.** Write down the hypothesis and analysis plan *before* running the experiment. Saves you from post-hoc storytelling.

---

## 13. Cost and Timeline

| Experiment | LLM $ | Engineer days |
|---|---|---|
| E1 — LongMemEval | 250 | 2 |
| E2 — LoCoMo | 150 | 1 |
| E3 — Token scaling | 50 | 1 |
| E4 — Context rot | 100 | 1 |
| E5 — Rule quality | 80 | 1.5 |
| E6 — Downstream lift | 400 | 3 |
| E7 — Isolation fuzz | 0 | 1 |
| E8 — Resumption | 60 | 2 |
| **Ablations** (across all) | 300 | 2 |
| **Infrastructure / adapters** | 0 | 5 |
| **Analysis + write-up** | 0 | 3 |
| **Total** | **~$1,400** | **~22 days (~4 weeks)** |

Add 50% buffer for re-runs and adapter bug-hunting → **~$2,100 and ~6 elapsed weeks** is realistic.

---

## 14. Recommended Order of Execution

1. **Week 1.** Build infrastructure: adapters for all 7 systems behind one Protocol, the grading harness, the results manifest.
2. **Week 2.** Run E3 (token scaling) and E7 (isolation fuzz) first. These are cheap, fast, and they validate the central design claims. If E3 doesn't show the bounded-context property, *stop and investigate before running anything else.*
3. **Week 3.** Run E1 (LongMemEval) and E4 (context rot). These are the headline numbers for any paper.
4. **Week 4.** Run E6 (downstream lift) — the experiment that justifies the existence of Dreaming.
5. **Week 5.** Run E2 (LoCoMo), E5 (rule quality), E8 (resumption).
6. **Week 6.** Run ablations, regenerate plots, write the evaluation section of the paper.

---

## 15. What "Publishable" Looks Like

For a workshop paper (e.g., NeurIPS Workshop on Agentic AI, ICLR LMRL Workshop): E1 + E3 + E6 is enough. ~2 weeks of work.

For a full conference paper (EMNLP, COLM, NeurIPS main): E1 + E2 + E3 + E6 + E7 + key ablations. ~4–6 weeks.

For a systems venue (SOSP, OSDI, MLSys): E3 + E4 + E7 + E8 + production telemetry from real deployments. The systems track values *system properties* over headline accuracy numbers; you can underweight E1/E2 there.

---

## 16. Failure Modes to Watch For

- **The "Mem0 already has a hosted API" trap.** Hosted Mem0 may use a different (and improving) model under the hood. Always use self-hosted Mem0 in pinned versions, or document the date and version of the hosted endpoint.
- **The "different chunking" trap.** Some baselines chunk at 256 tokens, others at 512. Standardize chunking parameters across baselines or it's not a fair fight.
- **The "prompt template" trap.** A small change to the system prompt can move accuracy by 5+ points. Use the exact same prompt template for all systems; only the memory context block differs.
- **The "API rate limit during weekend" trap.** Run experiments during business hours with explicit rate-limit handling. Bake in retries with exponential backoff.
- **The "seed forgot to be set" trap.** Audit every result's manifest before publishing. If a seed is missing, the result is non-reproducible.
- **The "LLM judge is biased" trap.** Use *two* LLM judges (different families: GPT and Claude) and report agreement. Where they disagree, escalate to human.

---

## 17. Deliverables Checklist

By the end of the program you should have:

- [ ] A `benchmarks/` repository, public, with adapter for each baseline.
- [ ] Eight `results/` directories with raw outputs, grader decisions, plots, and YAML manifests.
- [ ] A `results.csv` summarizing every (experiment, system, model, seed) cell.
- [ ] An `evaluation.tex` (or `evaluation.md`) write-up with the tables from §2–§9.
- [ ] A pre-registration document filed (in repo, dated, hashed).
- [ ] A Jupyter notebook reproducing every plot from the raw results.

If any of these is missing, the evaluation is not done.

---

*End of evaluation plan.*
