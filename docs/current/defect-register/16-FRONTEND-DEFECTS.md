# 16. Frontend Architecture — Defect Register

> **What this document is:** defects in the React SPA — routing, state, fetching,
> rendering cost and the build — plus the improvements that would make the app faster and
> cheaper to work on.
> **Source document:** [`16-frontend.md`](../16-frontend.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`.
> **Context:** the app ships with **no error boundary, no test runner and no working
> lint**. Those three absences shape everything below.

---

## How to read this file

- **✅ Verified** — the code or config was read on 2026-09-01 and the claim held.
- **📄 Doc-reported** — from `16-frontend.md`, not independently re-checked.
- Performance items here are unusually concrete: the document measured them. Where a
  number is quoted, it comes from reading the component, not from a benchmark.

---

## Contents

1. [Summary](#1-summary)
2. [T0 — The app can blank out and nobody would know](#2-t0--the-app-can-blank-out-and-nobody-would-know)
3. [T1 — Broken behaviour](#3-t1--broken-behaviour)
4. [T2 — Dead code and unused dependencies](#4-t2--dead-code-and-unused-dependencies)
5. [T3 — Performance](#5-t3--performance)
6. [Improvements](#6-improvements)
7. [Suggested order of work](#7-suggested-order-of-work)

---

## 1. Summary

| Tier | Theme | Count | When to do it |
|---|---|---|---|
| [T0](#2-t0--the-app-can-blank-out-and-nobody-would-know) | The app can blank out and nobody would know | 4 | **Now** — all four are small |
| [T1](#3-t1--broken-behaviour) | Broken behaviour | 7 | Before the next release |
| [T2](#4-t2--dead-code-and-unused-dependencies) | Dead code and unused dependencies | 5 | Free |
| [T3](#5-t3--performance) | Performance | 7 | When the page in question is next touched |

**Total: 23 defects, 10 improvements.**

The three to read first:

- **[FE-01](#fe-01--there-is-no-error-boundary)** — one render throw blanks the entire
  application, with no message.
- **[FE-04](#fe-04--if-you-forget-env-development-talks-to-production)** — the API client's
  fallback base URL is the production gateway.
- **[FE-17](#fe-17--the-webgl-background-never-sleeps)** — 6,300 matrix writes per frame
  plus a bloom pass, in the entry chunk, never cancelled.

---

## 2. T0 — The app can blank out and nobody would know

### FE-01 — There is no error boundary

**✅ Verified · High**

Grepping the whole `frontend/src` tree for `ErrorBoundary` or `componentDidCatch` returns
nothing.

In React 18, an uncaught render error unmounts the entire tree. So a single bad field in a
single API response — a null where an object was expected — blanks the **whole
application**, with a white page and no message. The user's only recourse is a refresh,
which reproduces it.

There is also no `<Suspense>` boundary below the router, so a slow lazy chunk blanks the
shell in the same way.

- app-wide
- [`frontend/src/router/index.tsx:116`](../../../frontend/src/router/index.tsx:116) — no Suspense below here
- Also recorded as **D-38** in the platform register

**Fix:** one `ErrorBoundary` around `MainLayout`'s children, and a second around the
router. Perhaps forty lines, and it converts every future render bug from "the app is
broken" into "this page is broken".

---

### FE-02 — `npm run lint` cannot run

**✅ Verified · High**

`package.json` declares:

```json
"lint": "eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0"
```

and `eslint`, `@typescript-eslint/*`, `eslint-plugin-react-hooks` and
`eslint-plugin-react-refresh` are all installed. There is **no ESLint config file
anywhere** in the repository.

So the command fails immediately, and there is no lint gate at all.

`eslint-plugin-react-hooks` in particular would have caught two of the defects in this
file — [FE-08](#fe-08--two-effects-have-wrong-dependency-arrays) is exactly what the
exhaustive-deps rule exists for.

- [`frontend/package.json`](../../../frontend/package.json)
- Also recorded as **D-39** in the platform register

**Fix:** add `.eslintrc.cjs`. Every plugin is already installed.

---

### FE-03 — There is no test runner

**✅ Verified · High**

Two `.test.ts` files exist and both import from `vitest`. Neither `vitest` nor `jest`
appears anywhere in `package.json`. There is no `test` script.

`useExecutionEvents.test.ts` even documents the missing setup in its own header:

```ts
* To run: install vitest (`npm install --save-dev vitest ...`) then `npx vitest run`.
```

Two knock-on effects:

- `tsconfig.json` **excludes** `*.test.ts`, so the tests are not type-checked by
  `npm run build` either. `useExecutionEvents.test.ts`'s local `_INITIAL` is already missing
  the `spans` field added later to `ExecutionEventState` — it would not compile.
- `cortex-helpers.ts` is imported only by its own test. It is tested dead code.

- [`frontend/src/hooks/useExecutionEvents.test.ts`](../../../frontend/src/hooks/useExecutionEvents.test.ts)
- [`frontend/src/components/agent/cortex-helpers.test.ts`](../../../frontend/src/components/agent/cortex-helpers.test.ts)
- Also recorded as **D-40** in the platform register

**Fix:** `npm i -D vitest jsdom`, add `"test": "vitest run"`, drop the `exclude`.

---

### FE-04 — If you forget `.env`, development talks to production

**📄 Doc-reported · High**

`api.client.ts` falls back to `https://gateway.hirebuddha.com/api/v1` when no base URL is
configured.

A developer who clones the repository and runs `npm run dev` without creating `.env` gets a
local UI issuing **writes against production**, with no warning of any kind.

Compounding it: there are **two** base-URL variables with different rules —
`VITE_API_BASE_URL` must include `/api/v1`, `VITE_API_URL` must not because the code appends
it — and the second is undocumented in `.env.example`.

- [`frontend/src/services/api.client.ts`](../../../frontend/src/services/api.client.ts)

**Fix:** fall back to `http://localhost:8001` and warn on the console. A wrong local URL is
a five-second fix; a production write is not.

---

## 3. T1 — Broken behaviour

### FE-05 — Three legacy redirects emit a literal `:id`

**✅ Verified · Medium**

```tsx
<Route path="/agents/:id"    element={<Navigate to="/ai/entities/edit/:id" replace />} />
<Route path="/workflows/:id" element={<Navigate to="/ai/entities/edit/:id" replace />} />
<Route path="/execute/:type/:id" element={<Navigate to="/ai/execute/:id" replace />} />
```

`<Navigate>` does not interpolate route parameters. Any old bookmark hitting these lands on
a URL containing the literal string `:id`, which matches nothing and falls through to the
catch-all.

The correct pattern already exists in the same file — `ExecutionRedirect` reads `useParams`
and builds the target.

- [`frontend/src/router/index.tsx:213`](../../../frontend/src/router/index.tsx:213), [`:214`](../../../frontend/src/router/index.tsx:214), [`:227`](../../../frontend/src/router/index.tsx:227)

---

### FE-06 — Bad JSON in the IO-contract fields silently kills the save

**📄 Doc-reported · Medium**

`EntityConfigurationTabs` calls `JSON.parse` on the input/output schema textareas with **no
try/catch**. A malformed schema throws inside the save handler, the save never completes,
and — with no error boundary ([FE-01](#fe-01--there-is-no-error-boundary)) — the user may
get a blank page instead of a validation message.

- [`frontend/src/pages/ai/EntityConfigurationTabs.tsx:682`](../../../frontend/src/pages/ai/EntityConfigurationTabs.tsx:682)

---

### FE-07 — Half the pages bypass `apiClient` and lose token refresh

**📄 Doc-reported · High**

`apiClient` implements the 401 → refresh → retry interceptor. Everything in
`pages/streaming/` and the lookups in `PhonePool.tsx` use raw `fetch`.

So on those pages, the moment the 30-minute access token expires, requests start failing
with 401 and **do not recover** — while the rest of the app silently refreshes and carries
on. The user sees one area of the product break for no visible reason.

- [`frontend/src/pages/streaming/`](../../../frontend/src/pages/streaming/)
- [`frontend/src/pages/PhonePool.tsx`](../../../frontend/src/pages/PhonePool.tsx)

---

### FE-08 — Two effects have wrong dependency arrays

**📄 Doc-reported · Medium**

| Effect | Problem |
|---|---|
| `MainLayout`'s submenu auto-open | mutates a copy of `openSubmenus` and omits it from the dependency array |
| `EntityFlow`'s planned-tool sync | reads `nodes` without depending on it |

Both are stale-closure bugs: the effect operates on a snapshot from an earlier render. The
symptoms are intermittent and hard to reproduce — a submenu that does not open, a tool that
does not appear on the canvas.

`eslint-plugin-react-hooks` is installed and would flag both, if there were a config
([FE-02](#fe-02--npm-run-lint-cannot-run)).

- [`frontend/src/components/layout/MainLayout.tsx:152`](../../../frontend/src/components/layout/MainLayout.tsx:152)–166
- [`frontend/src/pages/ai/EntityFlow.tsx:188`](../../../frontend/src/pages/ai/EntityFlow.tsx:188)–241

---

### FE-09 — Timestamps are wrong unless routed through a helper

**📄 Doc-reported · Medium**

The backend emits **naive UTC** ISO strings. `new Date(s)` parses them as browser-local, so
every timestamp is off by the viewer's UTC offset.

`parseServerDate` in `@/utils/datetime` exists to fix this. Nothing enforces its use, and a
missed call produces a plausible-looking wrong time rather than an error — which is the
hardest kind of bug to spot in a dashboard.

The root cause is upstream: all `DateTime` columns are naive
([DM-12](03-DATA-MODEL-DEFECTS.md#4-t2--wrong-types-and-dead-tables)).

---

### FE-10 — `getStepToolLogs` is a stub returning `false`

**📄 Doc-reported · Medium**

A function used by the execution detail view returns `false` for everything, so the tool
logs it is meant to surface never appear.

Combined with [EP-21](06-EXECUTION-PIPELINE-DEFECTS.md#ep-21--the-execution-detail-page-finds-artifacts-by-regex)
— artifacts located by regex rather than `run_id` — the run detail page is missing two
independent kinds of evidence about what a run actually did.

- [`frontend/src/pages/ai/ExecutionDetail.tsx:83`](../../../frontend/src/pages/ai/ExecutionDetail.tsx:83)

---

### FE-11 — The social login buttons do nothing

**📄 Doc-reported · Medium**

The Google and Microsoft buttons on the login page have **no handler**. They render, they
look clickable, and clicking them does nothing.

The backend has an OAuth path (`get_or_create_oauth_user`, `POST /auth/oauth/{provider}`),
so the feature is half-built rather than absent.

- [`frontend/src/pages/auth/LoginPage.tsx:76`](../../../frontend/src/pages/auth/LoginPage.tsx:76)–85

---

## 4. T2 — Dead code and unused dependencies

| ID | Delete | Notes | Status |
|---|---|---|---|
| **FE-12** | `react-hook-form`, `zod`, `@hookform/resolvers`, `date-fns` | Four dependencies with **zero imports** anywhere in `src/`. Confirmed by grep. The frontend README claims they are used | ✅ Verified |
| **FE-13** | [`pages/assets/AssetLibrary.tsx`](../../../frontend/src/pages/assets/AssetLibrary.tsx) | 314 lines, not routed, imported by nothing but its own CSS. Replaced by `Artifacts.tsx`. Also [PO-13](01-PRODUCT-OVERVIEW-DEFECTS.md#4-t2--dead-code-and-dead-surfaces) | ✅ Verified |
| **FE-14** | Six unmounted agent-kernel components | `PlanCandidatesCompare`, three `SupervisorAndBandit` widgets, `ProvenanceRibbon`, and the `cortex-helpers` module. All fully built, none mounted anywhere | 📄 Doc-reported |
| **FE-15** | The duplicate `.gap-1` rules | Defined three times in `global.css` (lines 312, 480, 579). The last wins, with the wrong value | 📄 Doc-reported |
| **FE-16** | The unused `response` variable in `useAuth` | Assigned from `authService.login` / `register` and never read. Would fail `noUnusedLocals` in a checked position | 📄 Doc-reported |

> Before deleting a component, confirm nothing imports it:
> `grep -rn "<ComponentName" frontend/src --include=*.tsx`

---

## 5. T3 — Performance

### FE-17 — The WebGL background never sleeps

**📄 Doc-reported · High**

`AnimatedBackground` does **6,300 matrix writes per frame** plus a full-screen bloom pass.
It has:

- no visibility check — it keeps rendering on a hidden tab,
- no `prefers-reduced-motion` check,
- and its `requestAnimationFrame` is **never cancelled on unmount**.

`three` (~600 KB minified) is imported by it, and `App.tsx` imports
`AnimatedBackground` **eagerly** — so 600 KB is in the entry chunk and must download before
the login form can render.

On a laptop this is a fan spinning up. On a phone it is battery drain and a slow first
paint on every visit.

- [`frontend/src/components/layout/AnimatedBackground.tsx`](../../../frontend/src/components/layout/AnimatedBackground.tsx)

**Fix, in order of value:** cancel the RAF on unmount, pause on `document.hidden`, respect
`prefers-reduced-motion`, and lazy-load the component so `three` leaves the entry chunk.

---

### FE-18 — `ExecutionDetail` walks the whole run tree on every render

**📄 Doc-reported · High**

1,111 lines with **zero** `useMemo`, `useCallback` or `React.memo`.
`findArtifactInTree`, `flattenChildSteps` and `collectChildLLMLogs` all run on every render
— recursing the entire child-run tree and regex-scanning every tool-log output string.

A 3-second poll drives those re-renders. So an open execution page performs a full tree walk
plus a regex sweep every three seconds, indefinitely.

- [`frontend/src/pages/ai/ExecutionDetail.tsx`](../../../frontend/src/pages/ai/ExecutionDetail.tsx)

---

### FE-19 — The execution poll never stops

**📄 Doc-reported · High**

The interval in the legacy body is created once with `[id]` dependencies and only **skips
work** when the status is terminal. The timer itself keeps firing forever.

A single open execution page issues roughly **1.3 requests per second, indefinitely** —
`AgentLoopExecutionDetail` polls three endpoints on a 3-second cycle on top of it. Leave a
tab open overnight and that is ~45,000 requests.

- [`frontend/src/pages/ai/ExecutionDetail.tsx:557`](../../../frontend/src/pages/ai/ExecutionDetail.tsx:557)

**Fix:** `clearInterval` on terminal status. One line, and it removes most of the app's
background load.

---

### FE-20 — `EntityConfigurationTabs` re-renders everything on every keystroke

**📄 Doc-reported · Medium**

1,780 lines, roughly **70 `useState`** in one component, zero `useMemo` and two
`useCallback`.

Every keystroke in any field re-executes the whole component function — including all the
`.filter()` calls for the tool list, the knowledge-base items and the CORTEX trees. Only
the active tab is mounted, but the work to decide what to render is done for all six.

- [`frontend/src/pages/ai/EntityConfigurationTabs.tsx`](../../../frontend/src/pages/ai/EntityConfigurationTabs.tsx)

---

### FE-21 — No caching layer, and fan-out on mount

**📄 Doc-reported · Medium**

| Pattern | Where |
|---|---|
| Fan-out on mount | `PhonePool` (5 requests), `AppAdminReports` (7), `TenantAdminReports` (6) |
| Refetch-everything after a mutation | `PhonePool`, `PlatformManagement`, `ToolManagement` |
| No cache at all | everywhere — navigating away and back refetches from scratch |
| N+1 on the entity canvas | `EntityFlow.fetchLibraries` pulls **all** entities and **all** tools every time the Hierarchy tab mounts |

The canvas one is the sharpest: fine at 50 entities, painful at 5,000, and it re-runs on
every tab switch.

---

### FE-22 — `recharts` may be duplicated across 13 chunks

**📄 Doc-reported · Medium**

`React.lazy` per route is right, and each page is its own chunk. But there is no
`manualChunks` configuration, so whether `recharts` is hoisted into a shared chunk or copied
into each of the 13 report chunks is left to Rollup's defaults.

`index.html` additionally blocks on a Google Fonts stylesheet and the Razorpay script on
**every** page load, including pages that will never take a payment.

---

### FE-23 — `useState(entity?.x)` only reads the prop once

**📄 Doc-reported · Medium**

`EntityConfigurationTabs` initialises roughly 70 state variables from props. `useState`
reads its initial value **once**, on first render.

Today the parent guards against mounting before the entity loads. Any change that removes
that guard produces a silently empty form — the user edits blank fields and saves them over
a real entity.

---

## 6. Improvements

### FE-I1 — Add an error boundary, a lint config and a test runner

**Effect: large, and it is one afternoon.**
[FE-01](#fe-01--there-is-no-error-boundary),
[FE-02](#fe-02--npm-run-lint-cannot-run),
[FE-03](#fe-03--there-is-no-test-runner). All three dependencies are already installed;
what is missing is configuration.

Do these first. Every other item in this file is easier to fix afterwards, and two of them
would have been caught automatically.

### FE-I2 — Stop the polls

**Effect: large, immediate.** [FE-19](#fe-19--the-execution-poll-never-stops). Clear the
interval on terminal status. Then, when the SSE stream gains replay
([GW-I7](13-GATEWAY-AND-REALTIME-DEFECTS.md#gw-i7--give-sse-an-event-id-and-a-short-replay-buffer)),
the polling can be removed entirely rather than merely stopped.

### FE-I3 — Adopt a query cache

**Effect: large.** [FE-21](#fe-21--no-caching-layer-and-fan-out-on-mount).
`@tanstack/react-query` would remove most of the polling, all of the manual `loading` state,
the refetch-everything-after-mutation pattern, and the fan-out on remount — replacing four
separate problems with one dependency.

It also gives request deduplication, which fixes the `EntityFlow` N+1 without changing that
component at all.

### FE-I4 — Lazy-load the background and make it sleep

**Effect: large for first paint and battery.**
[FE-17](#fe-17--the-webgl-background-never-sleeps). Four changes: cancel the RAF, pause on
hidden, respect `prefers-reduced-motion`, lazy-load it. The last one alone takes ~600 KB out
of the entry chunk, which is what stands between the user and the login form.

### FE-I5 — Memoise the two heavy components

**Effect: medium.** [FE-18](#fe-18--executiondetail-walks-the-whole-run-tree-on-every-render)
and [FE-20](#fe-20--entityconfigurationtabs-re-renders-everything-on-every-keystroke).
`useMemo` around the three tree walks in `ExecutionDetail`, and around the filter lists in
`EntityConfigurationTabs`. No restructuring needed — these are the two files where the
absence of memoisation costs the most.

### FE-I6 — Route everything through `apiClient`

**Effect: medium.** [FE-07](#fe-07--half-the-pages-bypass-apiclient-and-lose-token-refresh).
The streaming pages and `PhonePool` are the exceptions. Converting them gives those pages
401-refresh-retry, consistent error handling and one place to add request timing.

### FE-I7 — Generate the API types from the backend

**Effect: medium.** `types/index.ts` is hand-maintained against a FastAPI backend that
publishes an OpenAPI schema. Every backend field rename is a silent frontend break today —
the kind of drift that produced
[FE-09](#fe-09--timestamps-are-wrong-unless-routed-through-a-helper) and the
`_INITIAL`/`spans` mismatch in the untyped test.

### FE-I8 — Derive the sidebar from the router

**Effect: medium.** The sidebar and the route table are two separate lists with two separate
role predicates, and they **have already drifted** — `/reports/costing` is in one and not the
other, which is the only thing hiding an unguarded endpoint
([PO-04](01-PRODUCT-OVERVIEW-DEFECTS.md#po-04--any-logged-in-user-can-read-the-internal-cost-report)).

One list, with `showInNav` and `allowedRoles` per entry, makes that drift impossible.

### FE-I9 — Add `manualChunks` for the shared vendor libraries

**Effect: medium.** [FE-22](#fe-22--recharts-may-be-duplicated-across-13-chunks). An explicit
vendor chunk for `recharts`, `react`, `react-dom` and `react-router-dom` makes the bundle
layout deterministic instead of dependent on Rollup heuristics. Also defer the Razorpay
script to the wallet page.

### FE-I10 — Build the frontend for production

**Effect: large.** The SPA is served by `vite` (`npm run dev`) in production with `hmr:
false`. There is a `build` script and nothing uses it.

A dev server is slower, holds more memory, does no minification or asset hashing, and has a
much larger attack surface than a directory of static files behind Apache. Same item as
[SA-I1](02-SYSTEM-ARCHITECTURE-DEFECTS.md#sa-i1--serve-the-frontend-as-a-build-not-a-dev-server).

---

## 7. Suggested order of work

| Step | Work | Why here |
|---|---|---|
| **1** | FE-I1 — error boundary, ESLint config, vitest | One afternoon. Everything after this is safer, and two defects below get caught automatically |
| **2** | FE-I2 / FE-19, FE-04 | Stop the infinite poll; stop dev talking to production |
| **3** | T2 deletions — FE-12 to FE-16 | Free. Four unused dependencies and 314 lines of dead page |
| **4** | FE-05, FE-06, FE-10, FE-11 | Four small, visible bugs |
| **5** | FE-I4 / FE-17 | The background: lazy-load, cancel, pause. Biggest first-paint win |
| **6** | FE-I3 — react-query | Replaces four fetch problems with one library |
| **7** | FE-I5 / FE-18, FE-20 | Memoise the two heavy components |
| **8** | FE-I10 — production build, FE-I8 — one route list | The two structural changes |

---

## Where to go next

- [16 — Frontend architecture](../16-frontend.md) — the source document.
- [`DEFECT-REGISTER.md`](../DEFECT-REGISTER.md) — FE-01 is D-38, FE-02 is D-39, FE-03 is
  D-40, FE-12 is part of D-30.
- [17 — API reference](17-API-REFERENCE-DEFECTS.md) — the endpoints these pages call.
- [19 — Testing](19-TESTING-DEFECTS.md) — the backend picture, and why FE-02/FE-03 have no
  CI to run in.
- [01 — Product overview](01-PRODUCT-OVERVIEW-DEFECTS.md) — PO-01, PO-02 and PO-05 are
  frontend-visible product defects.
