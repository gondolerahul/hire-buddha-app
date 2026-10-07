# Frontend Track 6 — Memory v2 UI (parallel with backend T6)

> **Backend Track:** [`../08_track_6_memory_v2.md`](../08_track_6_memory_v2.md)
> **Owner:** Frontend engineer.
> **Duration:** 3 working days.
> **Behaviour change:** CORTEX node provenance + trust score visible;
>   Intelligence rule candidate/confirmed lifecycle visible; dreaming
>   indicator on run end.
> **Risk:** Low.

---

## 1. Objectives (functional)

After Frontend Track 6:

1. Every CORTEX node in `CortexExplorer` / `CortexTreeDetail` renders a
   **Provenance ribbon** showing source type, tool/URL, fetched-at,
   and a **trust score dot**.
2. IntelligenceTree nodes (under `📏 Instructions` / `🎯 Strategies` /
   `❤️ Preferences`) display a **status badge**: `candidate` /
   `confirmed` / `retired`.
3. Candidate rules show a small "promoted by next dream" hint.
4. The CORTEX viewport rendering in ExecutionDetail's right rail (when
   AgentLoop UI is on) **respects** the new `max_chars` bound and
   drops the legacy ops-help block.
5. A `dreaming_triggered` event appears as a small toast at the
   bottom of the run detail when a run finalises.
6. Memory assembly stats appear on the run header
   (`{knowledge: 5, intelligence: 3, episodic: 2}`).
7. Scope violation events (`agent.memory.scope_violation`) surface as
   an admin warning banner inside CortexExplorer for the affected
   tree.

---

## 2. Scope

### In scope

* New components:
  * `P11ProvenanceRibbon`
  * `P11TrustScoreDot`
  * `P11IntelStatusBadge` (`candidate`/`confirmed`/`retired`)
  * `P11MemoryAssemblyStrip` (in run header)
  * `P11DreamingToast`
  * `P11ScopeViolationBanner` (admin)
* Extend `useExecutionEvents` reducer with `memory_assembled`,
  `dreaming_triggered`, `intelligence_candidate_added`,
  `memory_scope_violation`.
* Augment `CortexExplorer` and `CortexTreeDetail` (existing pages) to
  show provenance and trust score.
* New service: `services/memory.service.ts` (today there's
  `cortex.service.ts`; we add a thin wrapper for the new endpoints).

### Out of scope

* Editing provenance / trust scores from UI.
* Configuring memory pipeline per entity (it's a backend default; UI
  shows it but isn't editable here — Phase 12 adds an editor).
* Visualisations of the Dreaming Engine's internal phases (Phase 12).

---

## 3. Architecture (technical)

### 3.1 Provenance ribbon on a CORTEX node

```
┌──────────────────────────────────────────────┐
│ 📎 Source: Tool (scraper_tool)               │
│   url: https://example.com/article           │
│   fetched: 2026-05-26 14:08 UTC              │
│   trust: ●●●○○  (0.62)                       │
└──────────────────────────────────────────────┘
```

* Strip at the top of any non-root node detail.
* Trust dot row shows 5 dots filled proportional to score.
* Hover: full Provenance JSON.

### 3.2 Intel status badge

In `CortexTreeDetail` for IntelligenceTree nodes:

```
🎯 "PROCESS with >5 children rarely completes within budget"
  [ confirmed ]   evidence: 14 runs
```

* `candidate` → amber dot, "Awaiting dreaming validation".
* `confirmed` → green dot.
* `retired` → grey, struck-through, hidden by default behind a "Show
  retired" toggle.

### 3.3 Memory assembly strip

In the run header (AgentLoop variant), under the cost gauge:

```
Memory: 📚5  💡3  🧪2  📜2     (~3140 tok)
```

Icons:

* 📚 knowledge refs
* 💡 intelligence rules
* 🧪 experience suggestions
* 📜 episodic context

### 3.4 Dreaming toast

When the run finalises (any terminal state) and the SSE
`dreaming_triggered` event fires for the entity, render a non-modal
toast (using framer-motion):

```
🌙 Dreaming Engine scheduled for this agent
  → expect new instructions / strategies shortly
```

Click → opens IntelligenceTree for that entity.

### 3.5 Scope violation banner

In `CortexTreeDetail`, when the tree has had a recent
`memory_scope_violation` event:

```
⚠️ A child run attempted to write outside its scope.
   Subtree: <root_id>  Attempt: <parent_id>
   Time: 2 min ago
```

Admin-only.

---

## 4. Detailed deliverables

### 4.1 FE-T6-1 — Reducer extension (Day 1 AM)

```ts
case 'memory_assembled': {
  return { ...s, memoryStrip: {
    knowledge: e.knowledge_refs,
    intelligence: e.intelligence_rules,
    episodic: e.episodic_context,
    prompt_chars: e.prompt_chars,
  } };
}
case 'dreaming_triggered': {
  return { ...s, dreamingTriggered: { entity_id: e.entity_id, reason: e.reason } };
}
case 'intelligence_candidate_added': {
  return { ...s, intelligenceCandidates: [...s.intelligenceCandidates, e] };
}
case 'memory_scope_violation': {
  return { ...s, scopeViolations: [...s.scopeViolations, e] };
}
```

### 4.2 FE-T6-2 — `P11ProvenanceRibbon` + `P11TrustScoreDot` (Day 1 PM)

Reads the `provenance` block from a CORTEX node's `source_ref`:

```ts
const provenance = node.source_ref?.provenance as Provenance | undefined;
```

If absent, renders nothing (legacy nodes don't have it).

### 4.3 FE-T6-3 — CortexTreeDetail update (Day 2 AM)

* Inject `P11ProvenanceRibbon` into the node detail view.
* Inject `P11IntelStatusBadge` for Intelligence nodes.
* Add "Show retired" toggle.

### 4.4 FE-T6-4 — `P11MemoryAssemblyStrip` (Day 2 PM)

* Reads from `view.memoryStrip` reducer state.
* Tiny inline component in the run header.

### 4.5 FE-T6-5 — `P11DreamingToast` (Day 3 AM)

* Mount inside `ExecutionDetail` only when the run is terminal AND a
  `dreaming_triggered` event was observed.
* Auto-dismiss after 10s.

### 4.6 FE-T6-6 — `P11ScopeViolationBanner` (Day 3 AM)

* Admin-only banner inside `CortexTreeDetail`.
* Reads from `services/memory.service.ts::getRecentScopeViolations(treeId)`.

### 4.7 FE-T6-7 — `services/memory.service.ts` (Day 3 PM)

```ts
export const memoryService = {
  async listIntelligenceRules(entityId: string, status?: string)
    : Promise<IntelRule[]> { ... },
  async getRecentScopeViolations(treeId: string)
    : Promise<ScopeViolation[]> { ... },
  async getDreamingHistory(entityId: string, limit = 10)
    : Promise<DreamingRun[]> { ... },
};
```

### 4.8 FE-T6-8 — Tests + PR (Day 3 PM)

Per §9.

---

## 5. Database / schema changes

N/A (frontend).

---

## 6. API changes (consumed)

| Endpoint | Status | Where used |
|----------|--------|------------|
| `GET /api/v1/cortex/trees/{id}/nodes` (extended `source_ref.provenance`) | extended | `cortex.service` |
| `GET /api/v1/cortex/trees/{id}/scope_violations` | NEW | `memory.service` |
| `GET /api/v1/entities/{id}/dreaming_history` | NEW (admin) | `memory.service` |
| `GET /api/v1/entities/{id}/intelligence_rules?status=` | NEW | `memory.service` |
| SSE stream | extended (memory_*, dreaming_*) | events |

---

## 7. Telemetry events

None emitted from frontend.

---

## 8. Feature flags (consumed)

| Flag | Effect |
|------|--------|
| `memory.viewport_compact` | If OFF (legacy) → CORTEX viewport in right rail shows ops-help line; in T6+ the rail trusts the bounded render. No UI branch needed |
| `memory.dreaming_outcome_trigger` | If OFF → dreaming toast never shows |
| `memory.scope_policy_enforced` | If OFF → no scope violation events to render |

---

## 9. Tests

### 9.1 Unit

* `P11ProvenanceRibbon` renders absent-provenance gracefully.
* `P11TrustScoreDot` renders correct fill count for 0 / 0.4 / 0.7 / 1.0.
* `P11IntelStatusBadge` shows all three states; retired hidden by
  default.
* Reducer updates `memoryStrip` on `memory_assembled`.
* `P11DreamingToast` auto-dismisses.

### 9.2 Integration

* Open `CortexTreeDetail` for a fixture tree with provenance →
  ribbons appear; trust dots render.
* IntelligenceTree shows candidate + confirmed + retired with toggle.

### 9.3 E2E

* `memory-provenance.spec.ts` — open CortexExplorer; navigate to a
  scraper-tool-written knowledge node; confirm provenance ribbon
  shows `scraper_tool` source + URL + trust dot.

---

## 10. Acceptance criteria

1. CORTEX nodes show provenance when present.
2. Intelligence nodes show status badges.
3. Memory assembly strip renders in run header.
4. Dreaming toast appears on terminal runs when triggered.
5. Scope violation banner visible to admins when applicable.
6. Coverage ≥ 75% on new components.
7. Lighthouse a11y ≥ 90.

---

## 11. Effort (3 days)

| Day | Work |
|-----|------|
| 1 AM | Reducer extension |
| 1 PM | ProvenanceRibbon + TrustScoreDot |
| 2 AM | CortexTreeDetail update |
| 2 PM | MemoryAssemblyStrip |
| 3 AM | DreamingToast + ScopeViolationBanner |
| 3 PM | memory.service.ts + tests + PR |

---

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Old nodes lack provenance | H (expected) | UI looks blank | Render nothing (graceful) — by design |
| Trust score interpretation unclear | M | UX confusion | Tooltip: "Higher trust = more reliable source. Computed from source_type and history" |
| Dreaming toast spammy on rapid runs | L | UX | Debounce: max 1 toast per entity per 60s |
| Scope violation banner alarms wrongly | L | Confusing | Banner has dismiss + "expected if subtree merge in progress" link |

---

## 13. Dependencies

* **Upstream:** FE-T2, Backend T6.
* **Downstream:** FE-T9 KPI dashboard reads dreaming + intelligence
  metrics.

---

## 14. Open questions

* Should we visualise the Dreaming Engine's runs (timeline)? **Phase
  12.** Track 6 just shows the toast.
* Should trust scores be editable by admins? **No** in Phase 11;
  the value is computed by the backend.
