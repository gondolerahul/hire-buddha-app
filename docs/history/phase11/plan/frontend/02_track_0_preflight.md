# Frontend Track 0 — Pre-Flight (parallel with backend T0)

> **Backend Track:** [`../02_track_0_preflight.md`](../02_track_0_preflight.md)
> **Owner:** Any frontend engineer.
> **Duration:** 0.5 day.
> **Behaviour change:** None.
> **Risk:** None.

---

## 1. Objectives (functional)

After Frontend Track 0:

1. `frontend/package.json` is clean: no unused dependencies surface
   from the upcoming backend cleanup.
2. `frontend/src/types/index.ts` is **noted** for the upcoming split
   in FE-1 (no actual split yet).
3. A lint pass on `frontend/` produces zero warnings on `main` so the
   subsequent Tracks can ship with `--max-warnings 0`.

---

## 2. Scope

### In scope

* Run `npm run lint` and fix existing warnings (or add explicit
  `eslint-disable-next-line` with a justification).
* Confirm `npm run build` succeeds on `main`.
* Audit `frontend/src/services/*.ts` for any service that imports from
  a backend path that's about to disappear (e.g. nothing should be
  calling `from src.ai.worker import X`-equivalent endpoint paths —
  but verify that no frontend service uses an admin endpoint that
  the backend Track 0 might rename).
* Confirm `frontend/dist/` is in `.gitignore` (it should be).

### Out of scope

* Any new feature.
* Refactors.

---

## 3. Architecture (technical)

No architecture change.

---

## 4. Detailed deliverables

### 4.1 FE-T0-1 — Lint pass

```bash
cd frontend
npm run lint
```

Fix every warning. If the count is large, time-box to one hour and
file follow-ups; the bar for Phase 11 is "no NEW warnings introduced
by Phase 11 PRs".

### 4.2 FE-T0-2 — Audit for soon-to-break endpoints

Backend Track 0 doesn't change any HTTP endpoints, but does rename one
class. Confirm no frontend service relies on a stringly-typed import
that the backend might surface in error messages:

```bash
grep -RIn "CortexRouter\|MemoryRouter\|src\.ai\.worker" frontend/src/
```

Expected: 0 hits. If there are any, file a Track 9 cleanup follow-up.

### 4.3 FE-T0-3 — Bundle stat

Capture the current bundle size as a baseline so we can detect
regressions in later Tracks:

```bash
cd frontend
npm run build
du -sh dist/assets/*.js | sort -h
```

Record in `docs/phase11/plan/frontend/BASELINE_BUNDLE.md`. This is a
**reference**, not a gate.

---

## 5. Database / schema changes

N/A.

---

## 6. API changes

N/A.

---

## 7. Telemetry events

N/A.

---

## 8. Feature flags

N/A.

---

## 9. Tests

* `npm run lint` exits 0.
* `npm run build` exits 0.
* `npm run preview` boots locally and the existing routes render.

---

## 10. Acceptance criteria

1. Frontend builds clean on `main`.
2. Lint warnings = 0 (or each remaining warning has a justification
   comment).
3. Baseline bundle size recorded.

---

## 11. Effort

Half a day.

---

## 12. Risks

None.

---

## 13. Dependencies

* Upstream: none.
* Downstream: every other frontend Track depends on a clean baseline
  build.

---

## 14. Open questions

* None.
