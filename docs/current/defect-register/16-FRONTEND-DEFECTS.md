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
| [T0](#2-t0--the-app-can-blank-out-and-nobody-would-know) | The app can blank out and nobody would know | 7 | **Now** — all small |
| [T1](#3-t1--broken-behaviour) | Broken behaviour | 9 | Before the next release |
| [T2](#4-t2--dead-code-and-unused-dependencies) | Dead code and unused dependencies | 5 | Free |
| [T3](#5-t3--performance) | Performance | 7 | When the page in question is next touched |

**Total: 28 defects, 10 improvements.**

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

**✅ Verified · High** · **Status: fixed (2026-10-01)** — `components/ErrorBoundary.tsx` wraps
the router (*The application hit an error…*) and, inside `MainLayout`, each page (*This page
hit an error…*, with **Try again** and **Reload**); the page boundary clears itself when the
route changes. A `<Suspense>` inside `MainLayout` means a page chunk still loading shows
"Loading…" in the content area instead of blanking the shell. **Evidence:** live, a
deliberate throw added to the Costing Report for the test (and removed) showed the page-level
message with the sidebar intact; clicking Billing Settings in the sidebar cleared it and
rendered that page.

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

### FE-26 — The production build fails

**✅ Verified · High** · **Status: fixed (2026-10-01)** — found 2026-10-01 while starting this
register.

`npm run build` is `tsc && vite build`, and `tsc` failed with 22 errors, so no production
bundle could be built from the repository (`main` included):

| Errors | Where | Cause |
|---|---|---|
| 5 | `EntityConfigurationTabs.tsx` | The builder reads `reasoning_config.execution_mode`, `goal_validation_interval`, `confidence_threshold`, `max_replanning_attempts`, `self_reflection_enabled`; the backend declares them (`ai/schemas/reasoning.py`), the TypeScript type did not |
| 4 | `CortexExplorer.tsx` | `JellyButton.onClick` was typed `() => void`, but the page passes the click event to stop it bubbling (which works at runtime); and an unused `TYPE_ICONS` |
| 13 | `CortexTreeDetail`, `ToolManagement`, `IntegrationsPage`, `ExecutionDetail`, `useAuth` | Unused imports and variables under `noUnusedLocals` — including FE-10's stub and FE-16 |

**Fix (2026-10-01):** the five fields are on the `reasoning_config` type; `JellyButton`'s
`onClick` receives the event; the unused names are gone. **Evidence:** `npx tsc --noEmit`
reports 0 errors (22 before) and `npm run build` completes.

---

### FE-27 — A compiled `vite.config.js` shadows `vite.config.ts`

**✅ Verified · High** · **Status: fixed (2026-10-01)** — found 2026-10-01 while fixing FE-24.

`vite.config.js` and `vite.config.d.ts` — output of the composite `tsconfig.node.json` — were
committed next to `vite.config.ts`, with both `*.tsbuildinfo` files. Vite loads
`vite.config.js` **before** `vite.config.ts`, so any edit to the `.ts` (a proxy, a port, a test
setting) is silently ignored until someone recompiles. The two happened to match.

**Fix (2026-10-01):** the compiled files are deleted and gitignored; `tsconfig.node.json`
writes its output to `node_modules/.tmp/tsconfig.node` (a referenced project may not use
`noEmit`). **Evidence:** the FE-24 proxy change, made in `vite.config.ts` only, took effect
on the next dev-server start.

---

### FE-28 — Artifact previews put the access token in the URL

**✅ Verified · Medium** · **Status: open** — found 2026-10-01 while fixing FE-04.

`Artifacts.tsx`'s `getPreviewUrl` builds
`/api/v1/artifacts/{id}/download?token=<access token>` for previews that cannot send headers
(`<img>`, `<iframe>`). A token in a query string is written to proxy and server access logs
and to browser history, and is sent in the `Referer` header of any request the preview makes.
The backend accepts it (`get_current_user_from_query`).

- [`frontend/src/pages/artifacts/Artifacts.tsx`](../../../frontend/src/pages/artifacts/Artifacts.tsx) — `getPreviewUrl`

The run page's live stream does the same: `EventSource` cannot send headers, so
`/ai/executions/{id}/stream?token=…` carries the access token too.

**Fix:** fetch the preview with the `Authorization` header and show it from a `blob:` URL, or
have the API mint a short-lived, single-artifact (or single-stream) token.

---

### FE-04 — If you forget `.env`, development talks to production

**✅ Verified · High** · **Status: fixed (2026-10-01)** — worse than recorded: besides
`config/api.ts`, `ExecutionDetail.tsx` carried its own copy of the production fallback, the
artifact download and preview URLs used the undocumented `VITE_API_URL` (empty → a relative
`/api/...` URL), and the dev server proxied `/api`, `/reports` and `/artifact` to
`gateway.hirebuddha.com` — so even a correctly configured local app sent those requests to
production.

`api.client.ts` falls back to `https://gateway.hirebuddha.com/api/v1` when no base URL is
configured.

A developer who clones the repository and runs `npm run dev` without creating `.env` gets a
local UI issuing **writes against production**, with no warning of any kind.

Compounding it: there are **two** base-URL variables with different rules —
`VITE_API_BASE_URL` must include `/api/v1`, `VITE_API_URL` must not because the code appends
it — and the second is undocumented in `.env.example`.

- [`frontend/src/services/api.client.ts`](../../../frontend/src/services/api.client.ts)

**Fix:** fall back to `http://localhost:8000/api/v1` and warn on the console. A wrong local
URL is a five-second fix; a production write is not. *(Port corrected 2026-09-30: the gateway on
8001 was merged into the API on 8000.)*

**Done (2026-10-01):** `config/api.ts` falls back to `http://localhost:8000/api/v1` and warns
on the console; it also exports `API_ORIGIN`, which the artifact download and preview URLs
use instead of `VITE_API_URL` (gone), and `ExecutionDetail` uses `API_BASE_URL` instead of its
own fallback. The dev-server proxies target `VITE_PROXY_TARGET`, default
`http://localhost:8000`. `.env.example` documents both. **Evidence:** a dev server on :3020
with `VITE_API_BASE_URL=/api/v1` served the app through the proxy to the local API (the
Costing Report and Billing Settings loaded with the local data); an API-style request to
`/reports/…` reached the local API (JSON 404), not the gateway.

---

## 3. T1 — Broken behaviour

### FE-05 — Three legacy redirects emit a literal `:id`

**✅ Verified · Medium** · **Status: fixed (2026-10-01)** — a `ParamRedirect` fills the route's
`:params` into the target (`ExecutionRedirect` uses it too). **Evidence:** live,
`/agents/<id>` landed on `/ai/entities/edit/<id>` and `/execute/process/<id>` on
`/ai/execute/<id>`.

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

**✅ Verified · Medium** · **Status: fixed (2026-10-01)** — the schemas are parsed in a
`try`; on bad JSON the builder switches to the Basics tab, shows *The input or output schema
is not valid JSON: …* beside Save, and sends nothing. **Evidence:** live, `{bad json` in the
input schema of `report-writer` showed the message, the page stayed, and no request was made.

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

**✅ Verified · Medium** · **Status: fixed (2026-10-01)** — both effects now update state with
an updater instead of a copy from the render they were created in, and the lint rule passes
on both.

- `MainLayout`: the groups holding the current page are computed during render
  (`activeGroupKey`) and opened with `setOpenSubmenus(prev => …)`, so a submenu toggled in
  the meantime is not reverted.
- `EntityFlow`'s planned-tool sync works inside `setNodes(prev => …)`. Worse than recorded:
  it removed *every* tool node whose tool was not marked PLANNED — including `TOOL_CALL`
  steps of the stored plan, which the next save then dropped (an FE-25 path). It now removes
  only the nodes it added itself (`tool-…`), and a separate effect drops edges left without a
  node.

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

**✅ Verified · Medium** · **Status: fixed (2026-10-01)** — the stub could not work: tool logs
had no `step_name` to match on (LLM logs do).

A function used by the execution detail view returns `false` for everything, so the tool
logs it is meant to surface never appear.

Combined with [EP-21](06-EXECUTION-PIPELINE-DEFECTS.md#ep-21--the-execution-detail-page-finds-artifacts-by-regex)
— artifacts located by regex rather than `run_id` — the run detail page is missing two
independent kinds of evidence about what a run actually did.

- [`frontend/src/pages/ai/ExecutionDetail.tsx:83`](../../../frontend/src/pages/ai/ExecutionDetail.tsx:83)

**Fix (2026-10-01):** `tool_interaction_logs.step_name` (migration `fe10_tool_log_step_name`),
written by both tool paths in `step_executor` and returned by the API. The run page's timeline
shows each step's tool-call count, and the step panel lists its tool calls with input and
output (or error); tool logs are collected from child runs as well. Calls logged before the
change have no step. **Evidence:** `tests/integration/test_tool_metering.py::
test_a_tool_call_records_the_step_that_made_it` — a `calculator` step named *Add the
numbers* logs its call under that name; `npm run build` type-checks the page. Not shown
live: a run with tool calls needs Vertex, whose credentials had expired.

---

### FE-11 — The social login buttons do nothing

**📄 Doc-reported · Medium**

The Google and Microsoft buttons on the login page have **no handler**. They render, they
look clickable, and clicking them does nothing.

The backend has an OAuth path (`get_or_create_oauth_user`, `POST /auth/oauth/{provider}`),
so the feature is half-built rather than absent.

- [`frontend/src/pages/auth/LoginPage.tsx:76`](../../../frontend/src/pages/auth/LoginPage.tsx:76)–85

---

### FE-24 — Reloading any `/reports/*` page proxies the browser to the gateway

**✅ Verified · Medium** · **Status: fixed (2026-10-01)** — the `/reports` proxy has a `bypass`:
a request that accepts `text/html` (a page load) is served the SPA's `index.html`; everything
else still goes to the API's static mount. **Evidence:** a full load of
`http://localhost:3020/reports/costing` rendered the Costing Report (signed in as the
`app_admin`); `curl -H "Accept: text/html"` got the SPA, `Accept: application/json` the API.
Found 2026-09-29 while verifying PO-04.

The Vite dev server proxies every path starting with `/reports` to
`http://gateway.hirebuddha.com` — meant for the backend's static `/reports` mount (generated
research reports). The SPA's own report pages share that prefix: `/reports/costing` and every
`/reports/analytics/*` page. Client-side navigation works, but a full page load — a refresh,
a bookmark, a pasted link — never reaches the SPA. The dev server forwards it to the gateway,
which answers with the backend's static mount, not the app.

Observed locally: loading `http://localhost:3010/reports/costing` landed on
`https://gateway.hirebuddha.com`. Production serves the SPA through the same dev server
([SA-I1](02-SYSTEM-ARCHITECTURE-DEFECTS.md#sa-i1--serve-the-frontend-as-a-build-not-a-dev-server)),
so the same reload fails there.

- [`frontend/vite.config.ts`](../../../frontend/vite.config.ts) — `server.proxy['/reports']`

**Fix:** give the static mount a prefix the SPA does not use (for example
`/static-reports`), or proxy only requests that do not accept `text/html` (a `bypass`
function).

---

### FE-25 — Saving from the entity builder rewrites config it does not show

**✅ Verified · High** · **Status: fixed (2026-10-01)** — the builder saves the stored entity
with its edits laid over it; plan steps round-trip. Found 2026-09-29 while fixing PO-09.

`EntityConfigurationTabs.handleSave` rebuilds every config column from the builder's own
form state and sends it whole; the update replaces each column. So opening an entity and
pressing **Save** without touching anything changes it:

1. **Keys the builder does not show are dropped.** An entity with
   `governance.meta_review_interval: 5` (set through the API) had no `meta_review_interval`
   after an unchanged builder save — it silently fell back to the default of 3. The same
   applies to every declared knob the builder has no control for (`critic_cost_share_pct`,
   `max_concurrent_children`, `review_mechanism.critic_model_override`, …).
2. **Tool steps of a static plan lose their input.** For the deep-research `report-writer`,
   the stored plan has steps 2 and 3 (`TOOL_CALL`) with `prompt_template: "{{step_1}}"` and
   `input_dependencies: ["step_1"]`. The payload the builder sends (captured without sending
   it) has no `prompt_template` on either tool step, and step 3's dependency rewired to
   `step_2` — `convertNodesToSteps` derives dependencies from the graph's edges.

Seeded entities are the ones most exposed: they carry settings the builder cannot display.

- [`frontend/src/pages/ai/EntityConfigurationTabs.tsx`](../../../frontend/src/pages/ai/EntityConfigurationTabs.tsx) — `handleSave`, `convertNodesToSteps`

**Fix:** start the payload from the loaded entity and overlay the builder's edits, rather
than rebuilding it; keep each step's `prompt_template` and `input_dependencies` in the graph
nodes so they round-trip.

**Done (2026-10-01).** Three causes, not two:

1. **Unshown keys.** `utils/entityConfig.overlayConfig` lays each rebuilt config column over
   the stored one: keys the builder sets win (a cleared field clears), keys it does not know
   are kept.
2. **Plan steps.** A node loaded from a stored step carries that step; the save overlays the
   canvas's fields on it, so `prompt_template`, `reasoning_hint`, exit conditions and the rest
   survive. Edges are drawn from the steps' `input_dependencies` (they used to be a chain in
   list order, which rewired step 3 to step 2). An ACTION step's stored `prompt_template` is
   kept unless its description was edited — before, every save replaced the step's real
   instruction with its description. `hierarchy.children` entries keep their stored fields.
3. **The planned-tool sync** removed plan `TOOL_CALL` steps whose tool was not marked PLANNED
   (see FE-08).

Keeping stored keys means an entity carrying a key the API no longer accepts (PO-09's 422)
could not be saved. The builder only sends keys it knows, so such a 422 can only name keys
carried over: `EntityBuilder` drops exactly those (when every named key exists on the stored
entity), saves again and says *Removed retired setting(s) no longer used: …*. In the local
database 84 of 341 entities — all parity-test rows — carry the unread
`governance.async_child_dispatch`.

**Evidence:** live on `report-writer`, with `governance.meta_review_interval: 5` set first:
an unchanged save — once through the Hierarchy tab and Save Hierarchy, once straight from
Basics — kept `meta_review_interval: 5`, kept step 1's real prompt, and kept steps 2 and 3 as
`TOOL_CALL` on `{{step_1}}` depending on `step_1`. The other differences after the save were
defaults the form fills (personality sliders, `bio` from the description, `null` → empty).
The entity was restored afterwards. No unit test: the frontend has no test runner yet
(FE-03); the helpers in `utils/entityConfig.ts` are pure and ready for one.

---

## 4. T2 — Dead code and unused dependencies

| ID | Delete | Notes | Status |
|---|---|---|---|
| **FE-12** | `react-hook-form`, `zod`, `@hookform/resolvers`, `date-fns` | Four dependencies with **zero imports** anywhere in `src/`. Confirmed by grep. The frontend README claims they are used | ✅ Verified |
| **FE-13** | `pages/assets/AssetLibrary.tsx` | 314 lines, not routed, imported by nothing but its own CSS. Replaced by `Artifacts.tsx`. Also [PO-13](01-PRODUCT-OVERVIEW-DEFECTS.md#4-t2--dead-code-and-dead-surfaces) | ✅ fixed (2026-09-29, `9719f1b`) by PO-13 — deleted with its CSS and `asset.service.ts` |
| **FE-14** | Six unmounted agent-kernel components | `PlanCandidatesCompare`, three `SupervisorAndBandit` widgets, `ProvenanceRibbon`, and the `cortex-helpers` module. All fully built, none mounted anywhere | 📄 Doc-reported |
| **FE-15** | The duplicate `.gap-1` rules | Defined three times in `global.css` (lines 312, 480, 579). The last wins, with the wrong value | 📄 Doc-reported |
| **FE-16** | The unused `response` variable in `useAuth` | Assigned from `authService.login` / `register` and never read. Would fail `noUnusedLocals` in a checked position | ✅ fixed (2026-10-01) — it did fail the build (FE-26); the `register` one went with AU-08 (`8842901`), the `login` one with FE-26 |

> Before deleting a component, confirm nothing imports it:
> `grep -rn "<ComponentName" frontend/src --include=*.tsx`

---

## 5. T3 — Performance

### FE-17 — The WebGL background never sleeps

**✅ Verified · High** · **Status: fixed (2026-10-01)** — all four:

- the animation frame's id is kept and cancelled on unmount (the loop used to reschedule
  itself forever), and the geometries, materials, composer and renderer are disposed;
- the loop stops while the tab is hidden and resumes when it is shown (`visibilitychange`);
- with `prefers-reduced-motion: reduce` it renders one still frame and does not animate,
  following the setting if it changes;
- `App.tsx` loads it with `lazy`, so `three` is no longer in the entry chunk.

**Evidence:** `npm run build` — the entry chunk went from 794 KB (221 KB gzip) to 252 KB
(81 KB gzip); `AnimatedBackground` is its own 543 KB chunk. In the browser the canvas mounted
and drew its still frame. The running/paused frame rate could not be measured: the test
browser pane was itself hidden (`visibilityState: hidden`), where no animation frames fire at
all.

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

**✅ Verified · High** · **Status: fixed (2026-10-01)** — the artifact search, the step
flattening and the LLM- and tool-log collection are module-level pure functions, combined in
`deriveRunView(run)` and computed with `useMemo` once per fetched run. **Evidence:** the legacy
view of a finished deep-research run (switched to it for the test through its per-run flag,
then switched back) rendered *Execution Steps (2)* with the child agent's header row; the
file passes the hooks lint rule.

1,111 lines with **zero** `useMemo`, `useCallback` or `React.memo`.
`findArtifactInTree`, `flattenChildSteps` and `collectChildLLMLogs` all run on every render
— recursing the entire child-run tree and regex-scanning every tool-log output string.

A 3-second poll drives those re-renders. So an open execution page performs a full tree walk
plus a regex sweep every three seconds, indefinitely.

- [`frontend/src/pages/ai/ExecutionDetail.tsx`](../../../frontend/src/pages/ai/ExecutionDetail.tsx)

---

### FE-19 — The execution poll never stops

**✅ Verified · High** · **Status: fixed (2026-10-01)** — the interval runs only while the run is
not in a terminal state (`COMPLETED`, `FAILED`, `PARTIAL_COMPLETE`, `CANCELLED`) and restarts if
a refine makes it live again. Found on the way: the old interval refreshed only an explicit
list of states that left out `WAITING_ON_CHILDREN`, so a parent waiting on its children stopped
updating; every non-terminal state now refreshes. The agent-loop panel's own poll already
stops when the loop reports done. **Evidence:** on a finished run, the network log shows only
the page's initial fetch (twice, React StrictMode in development) over 10 s, on both the
agent-loop and the legacy view.

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

**✅ Verified · Medium** · **Status: fixed (2026-10-01)** — confirmed a live race, not only a
latent one: on an edit route the builder rendered the form *before* the fetch started (with
`entity` undefined), and only recovered because the loading spinner happened to unmount it.
Now the edit route starts in the loading state; the form is keyed on the entity's id, so a
different entity remounts it; a failed fetch shows the error instead of an empty form that
Save would have written over the entity; and the hierarchy graph is built once as initial
state rather than by an effect that replaced it after the first paint.

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
