# Phase 11 — Manual Test Checklist (Frontend)

> **Purpose:** Foolproof, click-through verification of every Phase 11 feature
> exposed in the SPA, assuming all Phase 11 feature flags are enabled.
> **Audience:** QA / engineer testing through `http://localhost:3000`.
> **Scope:** Frontend behaviour, backed by `backend/src/ai/phase11_router.py`.
> **Last verified against code:** 2026-05-29.

---

## How Phase 11 surfaces in the UI (read first)

Phase 11 is a **backend agent-kernel rewrite** with a thin, mostly **read-only
observability skin** on the frontend. It appears in exactly two places:

1. **A new sidebar group "Agent Kernel"** (admin-only) with 5 pages under
   `/admin/phase11/*`.
2. **A flag-gated revamp of the Execution Detail page** — when
   `agent_loop.enabled` resolves ON for a run, the flat step list is replaced by
   a live iteration timeline + agent-state rail. Critic chips, bandit badges,
   supervisor cards, plan candidates, memory strip, and the cost chart all render
   **inside that revamped page**.

### Two truths that make or break testing

- **Surfaces ≠ data.** Turning flags ON makes *surfaces* appear; you only see
  *meaningful content* after you **trigger a fresh execution** that runs through
  the new pipeline. Old runs created before the flags were on have no
  agent-loop telemetry.
- **`agent_loop.enabled` and `meta_agent.board_routing` default OFF.**
  "All flags enabled" only holds if you set those two as **global or company
  overrides** on the Feature Flags page — verify (Section A), don't assume.

### Roles

Admin roles that see the Agent Kernel group: `APP_ADMIN`, `PARTNER_ADMIN`,
`TENANT_ADMIN`. Non-admins must not see it and must be redirected away from
`/admin/phase11/*`.

### Routes & components quick reference

| Sidebar label | Route | Page component |
|---|---|---|
| KPI Dashboard | `/admin/phase11/kpi` | `pages/dashboards/Phase11KPI.tsx` |
| Meta-Agent Intelligence | `/admin/phase11/meta-intelligence` | `pages/admin/MetaIntelligencePage.tsx` |
| Cost Attribution | `/admin/phase11/cost` | `pages/admin/CostAttributionDashboard.tsx` |
| Feature Flags | `/admin/phase11/feature-flags` | `pages/admin/FeatureFlagsPage.tsx` |
| Risk & Exit | `/admin/phase11/risks` | `pages/admin/RiskAndExitPage.tsx` |
| (Execution detail revamp) | `/ai/executions/:id` | `components/agent/P11AgentLoopExecutionDetail.tsx` |

---

## Section 0 — Setup & configuration (do this first)

- [ ] **0.1** `./start_services.sh` from repo root. Confirm ports listening:
      `lsof -i :8000 -i :8001 -i :3000 -i :5433 -i :6379 | grep LISTEN`
- [ ] **0.2** Open `http://localhost:3000`, log in as an **admin**
      (`APP_ADMIN` / `PARTNER_ADMIN` / `TENANT_ADMIN`).
- [ ] **0.3** Sidebar shows a new **"Agent Kernel"** group with: KPI Dashboard,
      Meta-Agent Intelligence, Cost Attribution, Feature Flags, Risk & Exit.
- [ ] **0.4** **Config for real data:** AI provider creds set
      (`AI_MODEL_CREDENTIALS_GUIDE.md`), Arq worker running, DB migrated
      (`alembic upgrade head`). Without these, executions error and no
      agent-loop telemetry is produced.
- [ ] **0.5** Log in as a **non-admin**: confirm the Agent Kernel group is hidden
      AND a direct hit on `/admin/phase11/kpi` redirects to dashboard.

**Expected general behaviour:** no destructive change. Legacy execution view,
entity library, and CORTEX explorer still work; Phase 11 adds overlays + pages.

---

## Section A — Feature Flags page (`/admin/phase11/feature-flags`) — TEST FIRST

This page is your control panel; verify it before everything else.
**UI:** title "Feature Flags", 3 tabs — **Effective / Admin / Numeric** — plus a
**Refresh** button ("Re-fetch /feature_flags/me").

- [ ] **A.1** **Effective** tab shows resolved flags. Confirm these are **ON**:
      `agent_loop.enabled`, `critic_pipeline.v2_enabled`, `meta_review.v2_enabled`,
      `planner.v2_enabled`, `memory.v2_canonical`, `tools.resilience_v2_enabled`,
      `meta_agent.board_routing`.
- [ ] **A.2** **Numeric** tab shows: `bandit.epsilon` (0.10),
      `planner.n_candidates` (3), `critic_pipeline.budget_share_cap` (0.20),
      `meta_agent.testdriver_budget_usd` (3.00).
- [ ] **A.3** **Admin** tab: set/confirm a **global** override
      `agent_loop.enabled = true` (and `meta_agent.board_routing = true`). Save
      succeeds; row appears.
- [ ] **A.4** **Live-refresh:** open the app in a second browser tab, toggle a
      flag in the first, switch back to the second tab → value updates within
      ~60s (or on tab focus) with **no page reload**.
- [ ] **A.5** Delete an override row → effective value reverts to default.

**Config note:** Overrides persist server-side (`PUT/DELETE /feature_flags/{key}`).
A **global** `agent_loop.enabled=true` flips the new Execution Detail for all runs
in scope; a **company** override scopes to one tenant; a **per-run** override
(via `POST /api/v1/execute` with `override_feature_flags`) is the most surgical.

---

## Section B — AgentLoop Execution Detail (centerpiece)

**Precondition:** `agent_loop.enabled` ON, then **trigger a fresh execution** of a
PROCESS or AGENT entity (AI Workspace → Entity Library → run; or Executions page).

**UI changes to expect** (replaces legacy flat step list):
two-column layout — left **iteration timeline**, right **sticky Agent State rail**;
**iteration cards** (iteration #, executor badge, budget pressure, plan-fragment
step list, decision + cost footer); **Agent State rail** (4-segment budget bar:
tokens/USD/wall/iters, open subgoals, achieved subgoals, blockers, last
action/observation, reflections); a **resume indicator (↩)** on a resumed card.

- [ ] **B.1** Open a NEW run's detail page → new two-column layout renders
      (not legacy step list).
- [ ] **B.2** Watch a RUNNING run → iteration cards stream in live (SSE); budget
      bar + subgoals update (~2s) without manual refresh.
- [ ] **B.3** Let it complete → final output card appears; live polling stops on
      terminal state.
- [ ] **B.4** Open an **old** run (pre-flag) with global flag ON → new shell
      renders but Agent State rail is empty/skeleton (graceful — confirms why
      fresh runs are needed).
- [ ] **B.5** **Rollback:** set `agent_loop.enabled = false`, reload an execution
      → **legacy** flat step list renders, no new network calls.

**Behavioral change:** new runs are event-driven (SSE), not polled status; budget
is enforced and visible.

---

## Section C — Critic Pipeline (inside iteration cards)

**Precondition:** `critic_pipeline.v2_enabled` ON (default). Inspect a run's cards.

**UI:** a **Step Health strip** per card with up to four **verdict chips**
PRE / POST / ALIGN / SUPER (PASS green, REVISE amber, REJECT/BLOCK red);
**failure-tag chips** under POST on REVISE/REJECT (severity-tinted, tooltip with
suggestion); a **retry-strategy badge** ("↻ retry: DIFFERENT_MODEL"); a **critic
cost gauge** in the header (e.g. "Critic: $0.04 / $0.12, 33%") turning amber above
`critic_pipeline.budget_share_cap` (0.20).

- [ ] **C.1** Run an entity → verdict chips appear; hover shows
      concerns/suggestions.
- [ ] **C.2** Run a likely-to-fail post-critic (vague goal / hostile input) →
      REVISE/REJECT chip + failure-tag chips + retry badge.
- [ ] **C.3** Header gauge updates as cost accrues; cap line turns amber when
      breached.
- [ ] **C.4** (Admin) open the health-records view/link → per-iteration table
      (backed by `/executions/{id}/health_records`).

---

## Section D — Meta-Review + Bandit (in the timeline)

**Precondition:** `meta_review.v2_enabled` + `bandit.enabled` ON (default).
Component: `P11SupervisorAndBandit`.

**UI:** **Supervisor verdict card** between iterations at checkpoints
(CONTINUE / REPLAN / ABORT / PAUSE + confidence + reasoning); on REPLAN a
**"View replan diff"** action; a **bandit badge** on cards
("bandit chose: DAG (exploit, score 0.74)" — amber=explore, blue=exploit); a
**task-class tag** in the run header ("task: research_topic").

- [ ] **D.1** Run a multi-iteration entity → supervisor card at checkpoints;
      bandit badge on iterations.
- [ ] **D.2** Force a replan (drifting/off-topic entity) → REPLAN card + replan
      diff modal opens.
- [ ] **D.3** Click the bandit badge (admin) → bandit-arm state (backed by
      `/entities/{id}/bandit_state`): arms table with pulls/successes/avg
      cost/score.
- [ ] **D.4** Hover the bandit badge → tooltip shows `bandit.epsilon` (0.10).

---

## Section E — Planner v2 (plan candidates)

**Precondition:** `planner.v2_enabled` ON (default). Component:
`P11PlanCandidatesCompare`.

**UI:** a **"View plan candidates"** CTA on the planning iteration card; a compare
modal with **2–3 candidates side-by-side** (style badge, estimated cost,
**invariant-violation badges** when `planner.invariants_enforced`, **judge score**
when `planner.judge_enabled`), chosen candidate **starred**, rejected dimmed with
failed-invariant chips; a **plan-style tag** in the run header
("plan: DAG_PARALLEL (judge 0.78)").

- [ ] **E.1** Run an entity with dynamic planning → "View plan candidates" CTA
      appears.
- [ ] **E.2** Open the modal → 2–3 candidates side-by-side, chosen starred, costs
      + judge scores visible.
- [ ] **E.3** Find a run with a rejected candidate → invariant-violation chips
      explain why.

**Config note:** `planner.n_candidates` (=3) controls candidate count (info
tooltip).

---

## Section F — Memory v2 / CORTEX (`/cortex` "Memory Trees")

**Precondition:** `memory.v2_canonical` ON (default). Open CORTEX Explorer → a
tree → node detail.

**UI:** a **Provenance ribbon** on non-root nodes (source type, fetched-at,
**5-dot trust score**); **Intelligence status badges** on rule nodes
(`candidate` amber / `confirmed` green / `retired` grey behind a "Show retired"
toggle); a **memory-assembly strip** in the agent-loop run header
(📚 knowledge / 💡 intelligence / 🧪 experience / 📜 episodic + token estimate);
a **dreaming toast** ("🌙 Dreaming Engine scheduled") on terminal runs when
`memory.dreaming_outcome_trigger` ON; an admin **scope-violation banner** in a
tree when `memory.scope_policy_enforced` ON and a child wrote out of scope.

- [ ] **F.1** Open a CORTEX node written by a tool → provenance ribbon + trust
      dots render.
- [ ] **F.2** Open an Intelligence tree → candidate/confirmed badges; "Show
      retired" toggle works.
- [ ] **F.3** Complete an agent-loop run → memory strip in header; dreaming toast
      on completion.
- [ ] **F.4** Open an old node lacking provenance → ribbon absent (graceful, by
      design).

---

## Section G — Tool + Cost (`/admin/phase11/cost` + inline)

**Precondition:** `tools.cost_resolver_v2_enabled` + `tools.resilience_v2_enabled`
ON (default).

**UI:** **Cost Attribution dashboard** ("Cost by attribution") — breakdown by
planner / actor / critic / tool / etc., window + company/entity filters, top-runs
table; **tool status badges** (ACTIVE / EXPERIMENTAL / DEPRECATED) on tool
listings (Tool Registry, EntityBuilder selector), EXPERIMENTAL hidden for
non-opted-in companies; **resilience indicators** inline on step rows
(reformat-attempt / fallback-taken / final-empty) with tooltips.

- [ ] **G.1** Open `/admin/phase11/cost` → breakdown renders; changing the window
      re-renders the chart.
- [ ] **G.2** Older runs → "No attribution data" empty state (not a broken chart).
- [ ] **G.3** Open Tool Registry / EntityBuilder tool selector → status badges
      visible; experimental tools gated.
- [ ] **G.4** Run something that triggers a tool retry/fallback → resilience icon
      on the step row with tooltip.

**Known caveat:** `tools.cost_attribution_required` is **OFF** and `CostLedger.add`
is not wired into every non-tool cost site, so some non-tool attribution slices
may be sparse — expected, not a regression.

---

## Section H — Meta-Agent Intelligence (`/admin/phase11/meta-intelligence`)

**Precondition for live data:** `meta_agent.board_routing` ON + crons
(`skill_promotion_scan`, `meta_agent_prompt_evolution`) having run.
**UI:** title "Meta Intelligence", 3 tabs — **Anti-Patterns / Skill Candidates /
Prompt Candidates**.

- [ ] **H.1** **Anti-Patterns** tab → lists anti-patterns with severity/evidence
      (may be empty on a fresh DB).
- [ ] **H.2** **Skill Candidates** tab → proposed chains; **Promote** action
      exists.
- [ ] **H.3** **Prompt Candidates** tab → HITL queue; **Approve & Apply** /
      **Reject** (expect two-step confirmation on approve — destructive).
- [ ] **H.4** Promote a skill candidate → new SKILL entity appears in Entity
      Library as **DRAFT**.
- [ ] **H.5** Entity Library shows a **DRAFT** filter/badge + "Promote to ACTIVE"
      action (gated by `meta_agent.draft_lifecycle`).

**Caveat:** Most data-dependent page. Empty states are legitimate on a fresh DB
with no board runs.

---

## Section I — KPI Dashboard (`/admin/phase11/kpi`)

**UI:** title "Phase 11 KPI", **6 tabs** — Runs, Cost, Critic, Meta, Memory, Loop —
plus a date-range (`since`) control.

- [ ] **I.1** **Runs / Cost / Critic / Meta** tabs → charts render from
      `/admin/kpi/{runs,cost,critic,meta_agent}` (populated once runs exist).
- [ ] **I.2** **Memory** and **Loop** tabs → show a **"Grafana / Metabase panels
      wire-up deferred"** placeholder. ⚠️ **Expected, not a bug** — no
      `/admin/kpi/memory` or `/admin/kpi/loop` endpoint exists yet.
- [ ] **I.3** Change the `since` window → the 4 working tabs re-query.

---

## Section J — Risk & Exit (`/admin/phase11/risks`)

**UI:** title "Programme Risk & Exit", **3 sections** — Risk Indicators (table +
chart), Exit Checklist, Decision Log. Polls every 60s, paused when tab hidden.

- [ ] **J.1** Risk indicators table renders canary watches: **R-PRG-3**
      (critic false-pass rate), **R-PRG-5** (critic cost share), **R-PRG-8**
      (meta-agent promotion reject rate).
- [ ] **J.2** Exit Checklist section renders exit criteria
      (`/admin/exit_checklist`).
- [ ] **J.3** Decision Log section lists programme decisions
      (`/admin/decisions`, GET + POST).
- [ ] **J.4** Leave the tab open ~60s → auto-refresh updates without reload;
      switching away pauses polling.

---

## Section K — Flag-degradation regression sweep (prove rollback works)

Turn each flag **OFF** on the Feature Flags page; confirm the UI degrades cleanly
(no broken half-built widgets) within ~60s, no console errors, no blank crashes.

- [ ] **K.1** `agent_loop.enabled` OFF → Execution Detail reverts to legacy step
      list.
- [ ] **K.2** `critic_pipeline.v2_enabled` OFF → step-health strip / verdict chips
      disappear.
- [ ] **K.3** `meta_review.v2_enabled` OFF → supervisor verdict cards stop
      rendering.
- [ ] **K.4** `bandit.enabled` OFF → bandit badge disappears.
- [ ] **K.5** `planner.v2_enabled` OFF → "View plan candidates" CTA hidden.
- [ ] **K.6** `memory.dreaming_outcome_trigger` OFF → no dreaming toast on run end.
- [ ] **K.7** `tools.resilience_v2_enabled` OFF → resilience icons stop appearing.
- [ ] **K.8** `meta_agent.board_routing` OFF → Meta-Agent data dries up (page
      stays reachable for observability).

---

## Top gotchas (read before you start)

1. **Surfaces ≠ data.** Flags ON make UI appear; you must **run fresh executions**
   (AI creds configured + Arq worker up) to populate timelines, critic chips,
   bandit, plan candidates, and KPI charts.
2. **`agent_loop.enabled` and `meta_agent.board_routing` are OFF by default** —
   confirm you actually overrode them (Section A.1) or the headline features
   won't show.
3. **KPI Memory/Loop tabs are intentional placeholders** (deferred) — not bugs.
4. **Meta-Agent Intelligence / anti-patterns are empty until board runs occur** —
   needs `meta_agent.board_routing` + crons.
5. **Old runs render the new shell but with empty state** under a global flag —
   use new runs for meaningful agent-loop content.
6. **`P11`-prefixed component names** are intentional canary naming (prefix
   removal deferred to Phase 12) — ignore in QA.
7. **Cost attribution may be partially sparse** for non-tool cost paths
   (`CostLedger.add` not yet wired everywhere; `tools.cost_attribution_required`
   is OFF) — expected.

---

## Sign-off

| Section | Tester | Date | Result (Pass/Fail) | Notes |
|---|---|---|---|---|
| 0 — Setup | | | | |
| A — Feature Flags | | | | |
| B — AgentLoop Execution Detail | | | | |
| C — Critic Pipeline | | | | |
| D — Meta-Review + Bandit | | | | |
| E — Planner v2 | | | | |
| F — Memory v2 / CORTEX | | | | |
| G — Tool + Cost | | | | |
| H — Meta-Agent Intelligence | | | | |
| I — KPI Dashboard | | | | |
| J — Risk & Exit | | | | |
| K — Flag-degradation sweep | | | | |
