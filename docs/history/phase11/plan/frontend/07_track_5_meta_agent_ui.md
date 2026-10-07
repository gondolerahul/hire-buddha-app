# Frontend Track 5 — Meta-Agent Board UI (parallel with backend T5)

> **Backend Track:** [`../07_track_5_meta_agent_board.md`](../07_track_5_meta_agent_board.md)
> **Owner:** Frontend engineer (senior).
> **Duration:** 8 working days.
> **Behaviour change:** Major. New nav section `/meta-agent` with five
>   pages; DRAFT entity lifecycle in EntityLibrary.
> **Risk:** Medium-High. Largest frontend Track. Mitigation: feature-
>   flag gate per tenant; canary first.
> **Goal mapping:** FE-G2, FE-G5.

---

## 1. Objectives (functional)

After Frontend Track 5:

1. New **`/meta-agent`** nav section visible to admins. Contains:
   * `/meta-agent` — landing dashboard (recent Meta-Agent runs +
     promotion outcomes + key metrics).
   * `/meta-agent/runs/:id` — Meta-Agent run detail with **Role
     Timeline**: RequirementChat → Curator → Architect → Critic →
     Validator → TestDriver → Promoter.
   * `/meta-agent/anti-patterns` — browse MetaIntelligenceTree
     anti-patterns.
   * `/meta-agent/skill-candidates` — list of proposed reusable
     SKILL chains, with a Promote action.
   * `/meta-agent/prompt-candidates` — HITL queue for Meta-Agent
     prompt evolution.
2. **EntityLibrary** filters now include **DRAFT** (admin-only) and
   shows a badge on DRAFT entities. A "Promote to ACTIVE" action
   (admin-only) appears on DRAFT cards.
3. **EntityBuilder** picks up the new `resolve_meta_cognition`
   defaults: the `meta_cognition` section in capabilities visibly
   shows the **opt-in vs auto-on** state. Existing entities backfilled
   by `p11t05_preserve_meta_cognition` show explicit checkboxes.
4. **TestDriver suite** results appear under the Promoter section of
   the Meta-Agent Run Detail.
5. **Curator decision** card shows REUSE / ADAPT / COMPOSE / CREATE
   plus the top candidate.
6. The Promoter decision (PROMOTED / REJECT / PENDING_HITL) shows the
   failed gates if any.
7. Anti-patterns added by the Critic during a run link back to the
   spec they triggered on.

---

## 2. Scope

### In scope

* New nav section + 5 new routes.
* New components (P11 prefix):
  * `P11RoleTimeline`, `P11RoleTimelineItem`
  * `P11CuratorDecisionCard`
  * `P11TestDriverSuiteCard`
  * `P11PromotionOutcomeCard`
  * `P11AntiPatternCard`, `P11AntiPatternBrowser`
  * `P11SkillCandidateCard`, `P11SkillCandidatesPanel`
  * `P11PromptUpdateCard`, `P11PromptUpdateQueue`
  * `P11DraftBadge` (EntityLibrary)
* Reducer extension for Meta-Agent events.
* New service: `services/meta.service.ts`.
* New service methods on `entity.service.ts` for the
  promote / reject / draft listing.
* Sidebar entry "Meta-Agent" gated by admin + `meta_agent.board_routing`
  flag.

### Out of scope

* Editing the Meta-Agent's template prompt from the UI (Phase 12;
  HITL via approve-prompt-candidate UI is the closest substitute).
* Composing a PROCESS from Curator's COMPOSE suggestion via UI
  drag-drop (Phase 12).
* Merging near-duplicate entities (Phase 12).
* Customising the test suite cases per entity (Phase 12).

---

## 3. Architecture (technical)

### 3.1 Meta-Agent Run Detail layout

```
┌──────────────────────────────────────────────────────────────┐
│ Meta-Agent Run #abc-123                                       │
│ Input: "create an agent that researches biotech IPOs"         │
│ Status: COMPLETED  Cost: $0.47/$5.00                          │
├──────────────────────────────────────────────────────────────┤
│  Role Timeline                                                │
│                                                                │
│  ●─ RequirementChat   ✓ 0.4s     "spec clarified"             │
│  │                                                             │
│  ●─ Curator           ✓ 0.9s     decision: CREATE             │
│  │                              top candidate: research-prod  │
│  │                              (similarity 0.62)             │
│  │                                                             │
│  ●─ Architect         ✓ 4.2s     drafted entity (3 steps)     │
│  │                                                             │
│  ●─ Critic            ⚠ 2.1s    verdict: REVISE → PASS (r2)   │
│  │                              concerns: 2 medium addressed  │
│  │                                                             │
│  ●─ Validator         ✓ 0.3s    all 8 invariants green        │
│  │                                                             │
│  ●─ TestDriver        ✓ 12s     suite: 5/5 cases passed        │
│  │                              breakdown: smoke/boundary…    │
│  │                                                             │
│  ●─ Promoter          ✓ PROMOTED → entity_id: xxx-yyy          │
│                                                                │
├──────────────────────────────────────────────────────────────┤
│ Final entity: research-biotech-ipos-1.0.0                     │
│ [ Open in EntityLibrary ]                                     │
└──────────────────────────────────────────────────────────────┘
```

Two columns when wide: timeline on left (60%), details panel on right
(40%) showing whichever role is selected.

### 3.2 Anti-patterns browser

```
/meta-agent/anti-patterns

[ Filter: severity ▼ ]  [ Filter: entity_type ▼ ]   [ Search ]

┌────────────────────────────────────────────────┐
│ 📏 PROCESS with >5 children rarely completes   │
│   severity: high   evidence: 14 instances      │
│   last seen: 2 days ago                        │
│   suggestion: limit child count, increase      │
│               max_cost_usd by 2x               │
│   [ See instances ]                             │
└────────────────────────────────────────────────┘
... more cards ...
```

### 3.3 Skill candidates panel

```
/meta-agent/skill-candidates

┌────────────────────────────────────────────────┐
│ Skill candidate: search → scrape → summarise   │
│ frequency: 12 times in last 30 days            │
│ source entity: research-deep-1.2.1             │
│ confidence: high                                │
│                                                 │
│ Steps:                                          │
│   1. TOOL_CALL[web_search]                      │
│   2. TOOL_CALL[scraper_tool]                    │
│   3. ACTION (summarise)                          │
│                                                 │
│ [ Promote to SKILL entity ]  [ Dismiss ]        │
└────────────────────────────────────────────────┘
```

Promote → opens a slim EntityBuilder pre-filled with the chain, in
DRAFT status. User can tweak then save.

### 3.4 Prompt-Update queue

```
/meta-agent/prompt-candidates

┌────────────────────────────────────────────────┐
│ Prompt update candidate #5                     │
│ proposed by: prompt-evolution cron (2 days ago)│
│ evidence: 18 recent runs                        │
│ rationale: "agents miss anti-pattern checks   │
│            on adapt mode in 30% of cases"     │
│                                                 │
│ Diff (Meta-Agent system prompt):               │
│   - "ALWAYS validate before creating ..."       │
│   + "ALWAYS validate AND check Meta-Intelli-   │
│      gence anti-patterns before creating ..."  │
│                                                 │
│ [ Approve & Apply ]  [ Reject ]  [ View runs ] │
└────────────────────────────────────────────────┘
```

### 3.5 EntityLibrary DRAFT badge

Add `status === 'DRAFT'` to the card chip; "Promote" CTA (admin) at
card hover. Filter chip in the toolbar: `All | Active | Draft |
Deprecated`.

### 3.6 EntityBuilder meta-cognition section

Today there's likely a `MetaCognition` accordion in the Capabilities
tab. After T5:

* "Registry Search" defaults OFF for new AGENT/PROCESS; copy says
  "Allow this agent to discover and delegate to other agents."
* "Self-Modification" defaults OFF; copy says "Allow this agent to
  create or modify other agents. Reserved for Meta-Agent; opt-in
  only for trusted orchestrators."
* Existing entities backfilled by migration show explicit ON.

---

## 4. Detailed deliverables

### 4.1 FE-T5-1 — Sidebar + routes (Day 1 AM)

Add admin-only "Meta-Agent" section to the sidebar (existing
`MainLayout`). Register the 5 lazy routes.

### 4.2 FE-T5-2 — `services/meta.service.ts` (Day 1 PM)

```ts
export const metaService = {
  listAntiPatterns(filters): Promise<AntiPattern[]> { ... },
  listSkillCandidates(): Promise<SkillCandidate[]> { ... },
  listPromptCandidates(): Promise<PromptUpdateCandidate[]> { ... },
  approvePromptCandidate(id): Promise<void> { ... },
  rejectPromptCandidate(id): Promise<void> { ... },
  promoteEntity(entityId): Promise<{ ok: true }> { ... },
  rejectDraft(entityId, reason): Promise<void> { ... },
  promoteSkillCandidate(candidateId): Promise<{ entity_id: string }> { ... },
};
```

### 4.3 FE-T5-3 — `P11RoleTimeline` + `P11RoleTimelineItem` (Day 2)

Vertical timeline component. Each item has:

* Status dot (queued / running / done / blocked).
* Role name + duration + cost.
* Inline verdict if applicable (REVISE / PASS / etc).
* Click → opens the details rail.

Driven by Meta-Agent events:

```ts
case 'meta_role_started': { /* mark item running */ }
case 'meta_role_completed': { /* mark item done, store verdict */ }
case 'meta_test_case': { /* attach to TestDriver item */ }
case 'meta_testdriver_suite_completed': { /* finalise TestDriver */ }
case 'meta_promotion': { /* finalise Promoter */ }
case 'meta_curator_decision': { /* attach decision to Curator */ }
```

### 4.4 FE-T5-4 — Run detail components (Day 3)

* `P11CuratorDecisionCard`
* `P11TestDriverSuiteCard` (lists 5 cases + budget used)
* `P11PromotionOutcomeCard` (PROMOTED / REJECT / PENDING_HITL +
  failed gates list)

### 4.5 FE-T5-5 — Anti-Patterns browser (Day 4)

Page + `P11AntiPatternCard` + filter bar + "See instances" drawer
showing entities that triggered the anti-pattern.

### 4.6 FE-T5-6 — Skill Candidates panel (Day 5)

Page + card + Promote dialog (opens EntityBuilder pre-filled).

### 4.7 FE-T5-7 — Prompt-Update queue (Day 6)

Page + diff renderer (use a small Markdown-aware diff component;
syntax-highlight diff lines).

### 4.8 FE-T5-8 — EntityLibrary DRAFT + EntityBuilder updates (Day 7)

* DRAFT chip + filter.
* "Promote to ACTIVE" admin action.
* EntityBuilder MetaCognition section copy + default-off behaviour.
* Tests.

### 4.9 FE-T5-9 — Meta-Agent landing dashboard (Day 8 AM)

`/meta-agent` page: tiles for recent Meta-Agent runs, promotion
outcomes (last 7 days), top anti-patterns, pending prompt updates.
Each tile is a recharts-driven small chart.

### 4.10 FE-T5-10 — Tests + canary (Day 8 PM)

Per §9.

---

## 5. Database / schema changes

N/A (frontend).

---

## 6. API changes (consumed)

| Endpoint | Status | Where used |
|----------|--------|------------|
| `GET /api/v1/meta/anti_patterns` | NEW (backend T5) | `meta.service.listAntiPatterns` |
| `GET /api/v1/meta/skill_candidates` | NEW | `meta.service.listSkillCandidates` |
| `GET /api/v1/meta/prompt_candidates` | NEW | `meta.service.listPromptCandidates` |
| `POST /api/v1/meta/prompt_candidates/{id}/approve` | NEW | `approvePromptCandidate` |
| `POST /api/v1/meta/promote/{entity_id}` | NEW | `promoteEntity` |
| `POST /api/v1/meta/spec_critic/run-on-spec` | NEW (admin debug) | future |
| SSE stream | extended (meta_*) | events |

---

## 7. Telemetry events

Frontend tracks "Promote clicked" / "Reject prompt candidate clicked"
as analytics events (already plumbed via existing analytics service if
present; otherwise no-op).

---

## 8. Feature flags (consumed)

| Flag | Effect |
|------|--------|
| `meta_agent.board_routing` | Without it → nav section hidden; existing Meta-Agent runs still work but render in legacy mode |
| `meta_agent.draft_lifecycle` | Without it → DRAFT badge / Promote action hidden |
| `meta_agent.skill_promotion_cron` | Reads-only — controls whether the panel has data |
| `meta_agent.prompt_evolution_cron` | Reads-only — same |

---

## 9. Tests

### 9.1 Unit

* `P11RoleTimeline` renders the seven roles in order, status dots
  match state.
* `P11CuratorDecisionCard` shows the four decision types.
* `P11TestDriverSuiteCard` renders 5 cases; "budget exhausted" badge
  appears when applicable.
* `P11PromotionOutcomeCard` lists failed gates for REJECT.
* `P11AntiPatternCard` filters by severity / entity_type.
* `P11SkillCandidateCard` Promote opens EntityBuilder with pre-filled
  steps.
* `P11PromptUpdateCard` renders diff lines correctly.
* EntityLibrary: DRAFT filter shows only DRAFT entities for admin;
  hides for non-admin.

### 9.2 Integration

* Open `/meta-agent/runs/:id` for a fixture run → all 7 roles render
  → details rail updates on click.
* Promote a skill candidate → new SKILL entity appears in
  EntityLibrary as DRAFT.
* Approve a prompt update candidate → call sent → success toast +
  candidate removed from queue.

### 9.3 E2E (Playwright)

* `meta-agent-create-flow.spec.ts` — submit a NL request, watch the
  Role Timeline animate through all seven roles, confirm Promoter
  outcome PROMOTED, confirm the new entity appears in EntityLibrary.
* `meta-agent-blocked-by-critic.spec.ts` — submit a hostile input,
  expect Critic BLOCK + Promoter REJECT.

---

## 10. Acceptance criteria

1. Admin sidebar shows "Meta-Agent" with five sub-routes when
   `meta_agent.board_routing` is on.
2. Meta-Agent Run Detail renders the Role Timeline live.
3. Anti-patterns browser shows MetaIntelligence data with filters.
4. Skill candidates can be promoted → DRAFT entity created.
5. Prompt update candidates can be approved (HITL) or rejected.
6. EntityLibrary shows DRAFT badge to admins; Promote action works.
7. EntityBuilder Meta-Cognition section: defaults flipped to opt-in.
8. Lighthouse a11y ≥ 90 on all new pages.
9. Coverage ≥ 75% on new components.

---

## 11. Effort (8 days)

| Day | Work |
|-----|------|
| 1 | Sidebar + routes + meta.service skeleton |
| 2 | Role Timeline components + reducer events |
| 3 | Run detail composition (Curator/Test/Promoter cards) |
| 4 | Anti-Patterns browser + page |
| 5 | Skill Candidates panel + promote dialog |
| 6 | Prompt-Update queue + diff renderer |
| 7 | EntityLibrary DRAFT lifecycle + EntityBuilder updates |
| 8 | Meta-Agent landing dashboard + tests + PR |

---

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Diff renderer rendering arbitrary text triggers XSS | M | Security | Use a known sanitiser (DOMPurify; add dep); render only as text by default; "View HTML" requires opt-in |
| Anti-patterns list grows large | L | Slow | Pagination + filter by severity (default: high + critical) |
| Skill candidate promote → invalid SKILL spec | M | Builder save fails | Pre-fill is best-effort; user can edit before save |
| EntityBuilder default flip breaks existing forms | M | Old drafts lose flags | Form load coerces missing keys to backfilled true (matches backend migration) |
| Role Timeline with 8+ roles becomes vertical scroll | L | UX | Sticky details rail; collapse done roles by default |
| Prompt update approval is destructive | H | Bad prompt deployed | Two-step confirmation; HITL approval audit logged |

---

## 13. Dependencies

* **Upstream:** FE-T4 (timeline patterns), Backend T5 (endpoints +
  preserve migration).
* **Downstream:**
  * FE-T9 KPI dashboard pulls Meta-Agent metrics.

---

## 14. Open questions

* Should we render the Meta-Agent's *prompt* somewhere in the UI for
  inspection? **Decision:** yes, but read-only, on `/meta-agent`
  landing under "system prompt" accordion (admin-only).
* Should non-admin users see the Meta-Agent at all? **Decision:** the
  current Meta-Agent UI is admin-only end-to-end; Track 5 doesn't
  expand visibility.
* Where do REJECT-reasons surface in the UI? **Decision:** as a toast
  + an entry in the Promoter card; clicking the entry opens a modal
  with the full gate report.
