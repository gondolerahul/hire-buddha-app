# Remaining Defects — Phased Plan

> **What this document is:** the plan for every defect still open across the twenty
> registers after the [consolidated kernel/tools plan](CONSOLIDATED-KERNEL-TOOLS-PLAN.md)
> finished. It assigns each one to exactly one phase, says what "fixed" means for it, and
> lists the decisions the product owner has to take first.
> **Written:** 2026-10-07, on branch `roadmap-development-defect-fixes`, after re-verifying
> every register entry against the code in `backend/` and `frontend/`.
> **Status of record:** each register's status line and the [progress log](#progress-log)
> at the end of this file. The phases are named **H0–H11** ("hardening") so they cannot be
> confused with the consolidated plan's P0–P11.

---

## Contents

1. [Where things stand](#1-where-things-stand)
2. [What the re-verification changed](#2-what-the-re-verification-changed)
3. [The phases at a glance](#3-the-phases-at-a-glance)
4. [Decisions needed](#4-decisions-needed)
5. [The phases](#5-the-phases)
6. [How each fix is worked](#6-how-each-fix-is-worked)
7. [Progress log](#progress-log)

---

## 1. Where things stand

Re-verified against the code on 2026-10-07. Counts are register entries; the same defect
recorded in two registers counts twice.

| Status | Entries |
|---|---:|
| Fixed | 376 |
| **Open** | **87** |
| **Partly fixed** | **17** |
| Deferred by the product owner | 17 |
| Won't fix, accepted, or "correct as-is" | 10 |
| Invalid or moot | 11 |
| **Total** | **518** |

**To fix: 104 entries (87 open, 17 partly fixed), 96 distinct defects.** Eight are
duplicates of another entry in the list: API-03 = GW-01, TS-02 = IN-05, TS-03 = IN-18,
ON-09 = IN-17, ON-11 = TS-09, GW-13 = GW-06, TS-04 and TS-08 = FE-03. Plus **17 deferred**
(15 distinct — PO-19 and PO-20 duplicate GW-19 and GH-07, which are scheduled).

Fully closed registers: 02, 03, 06, 07, 09, 10, 11, 14, TOOL-LAYER and the PO-06 audit.

| Register | Open | Partly | Deferred | Phases |
|---|---:|---:|---:|---|
| [01 Product](01-PRODUCT-OVERVIEW-DEFECTS.md) | 1 | — | 6 | H2, H4, H6, H11 |
| [04 Auth](04-AUTH-RBAC-TENANCY-DEFECTS.md) | 2 | — | — | H2 |
| [05 Kernel](05-AGENT-KERNEL-DEFECTS.md) | 1 | — | — | H4 |
| [08 Memory](08-MEMORY-AND-CORTEX-DEFECTS.md) | — | — | 11 | H11 |
| [12 Voice](12-VOICE-AND-TELEPHONY-DEFECTS.md) | 10 | 4 | — | H5 |
| [13 Gateway](13-GATEWAY-AND-REALTIME-DEFECTS.md) | 9 | 3 | — | H0, H2, H6 |
| [15 Governance](15-GOVERNANCE-AND-HITL-DEFECTS.md) | 10 | 4 | — | H4, H7, H11 |
| [16 Frontend](16-FRONTEND-DEFECTS.md) | 3 | — | — | H1, H2, H9 |
| [17 API](17-API-REFERENCE-DEFECTS.md) | 8 | 1 | — | H0, H2, H8, H10 |
| [18 Infrastructure](18-INFRASTRUCTURE-AND-DEPLOYMENT-DEFECTS.md) | 16 | 3 | — | H1, H3, H4 |
| [19 Testing](19-TESTING-DEFECTS.md) | 14 | 2 | — | H0, H1, H10 |
| [20 Onboarding](20-ONBOARDING-AND-GLOSSARY-DEFECTS.md) | 13 | — | — | H0, H4, H10 |
| **Total** | **87** | **17** | **17** | |

### The critical ones

| Defect | Why it is first |
|---|---|
| [GW-01](13-GATEWAY-AND-REALTIME-DEFECTS.md#gw-01--no-webhook-signature-is-ever-verified-and-a-failure-would-not-block) / API-03 | No webhook signature is checked, and a failed check is ignored. Anyone who can reach `POST /webhook/inbound` runs any tenant's agents on that tenant's credit |
| [IN-05](18-INFRASTRUCTURE-AND-DEPLOYMENT-DEFECTS.md#in-05--the-repository-has-no-functioning-ci) / TS-02 | No CI. ~1,840 unit and ~375 integration tests, the layout lint, the type check and the frontend build run only by hand. The branch is 114 commits ahead of `origin`, unpushed |
| [IN-01](18-INFRASTRUCTURE-AND-DEPLOYMENT-DEFECTS.md#in-01--backups-are-monthly-and-on-the-same-disk-as-the-database) + [IN-02](18-INFRASTRUCTURE-AND-DEPLOYMENT-DEFECTS.md#in-02--the-backup-script-writes-to-a-path-that-does-not-exist-here) | Monthly backups, on the database's own disk, written to an old checkout's path. Nobody has shown that a usable backup exists |
| [VT-01](12-VOICE-AND-TELEPHONY-DEFECTS.md#vt-01--the-inbound-credit-gate-has-never-run) (partly) | The inbound voice credit check now runs but still fails open; with VT-08, inbound calls have no control that fails closed |

The High-severity entries that belong with them: GW-04 (a company UUID opens a live voice
session — no token check), AU-24 (the credential key's default is in the repo), GW-03
(webhook replays run twice), AU-25, VT-02, VT-03, GH-25, GH-07, GH-05, AK-08, MC-24
(deferred), IN-06…IN-09, TS-05, TS-06, FE-03.

---

## 2. What the re-verification changed

Every register entry that was not marked fixed was checked against the code, and the
fixed ones were sampled (every Critical fix held). The registers now carry these changes.

**Fixed in code but not recorded** — now marked fixed with the commit:
VT-06 (`66fe8bc`, TL-20), VT-07 (`86a95a0`), GH-02 (`c1eecb9`, BC-05), GH-12 (`b7644b7`),
GH-17 (`d71918d`, `902af7c`), GH-19 (`73afd55`, TL-21), API-01 (five commits in registers
04, 14, 01), API-02 (`fe8f1a6`, `e46bff3`), API-06 (`8842901`), IN-22 (`84dae64`), TS-07
(`3352625`), ON-13 (`ddd4912`), AK-04 (`dfe42d6`, with PC-01), AK-06 (`24b7fed`, with AK-05),
EP-14 (`909cdf4`, with TL-39), and AU-23's frontend half (`1fffde8`, `c61a44c`, FE-11).

**Partly fixed, not recorded:** VT-01, VT-13, VT-15, VT-21, GH-03, GH-15, GH-16, GH-21,
API-18, IN-14, TS-08.

**Invalid:** GW-05. uvicorn trusts `X-Forwarded-For` from `127.0.0.1` by default and takes
the address Apache appends, so the limiter keys on the real client.

**Not a defect** (the entries said so themselves): VT-18, VT-19, VT-20. **Accepted:**
API-14, TS-19.

**Open, and missed by the consolidated plan:** AK-08. The plan merged it into AK-05, whose
fix deleted the Perceiver and left `state.blockers` with no producer.

**Worse than recorded:** IN-17 (`agent_loop.py` is 1,496 lines against a 1,500 cap), ON-06
(the exercise asserts on a function that was deleted), IN-23 (`OTEL_SDK_DISABLED=true` does
not silence the exporter either).

**Unblocked:** FE-21 (`@tanstack/react-query` is installed, `895ddc8`; nothing uses it).

---

## 3. The phases at a glance

| Phase | Theme | Entries | Critical inside | Needs first |
|---|---|---:|---|---|
| [H0](#h0--clear-the-ground) | Clear the ground — deletions, no behaviour change | 9 | — | — |
| [H1](#h1--turn-on-the-lights) | Turn on the lights — CI and honest tests | 16 | IN-05, TS-02 | HD1 |
| [H2](#h2--close-the-open-doors) | Close the open doors — security | 9 | GW-01, API-03 | HD2–HD5 |
| [H3](#h3--keep-the-data-harden-the-host) | Keep the data, harden the host | 15 | IN-01, IN-02 | HD6, VM access |
| [H4](#h4--governance-and-hitl-that-hold) | Governance and HITL that hold | 12 | — | HD7, HD8, HD17 |
| [H5](#h5--voice-and-messaging) | Voice and messaging | 14 | VT-01 | HD9, HD10, HD13, HD14 |
| [H6](#h6--real-time-transport) | Real-time transport | 7 | — | HD11, HD12 |
| [H7](#h7--feature-flags-you-can-trust) | Feature flags you can trust | 3 | — | — |
| [H8](#h8--one-consistent-api-surface) | One consistent API surface | 5 | — | HD16 |
| [H9](#h9--frontend-data-layer) | Frontend data layer | 1 | — | — |
| [H10](#h10--documentation-and-onboarding) | Documentation and onboarding | 11 | — | after H1, H4 |
| [H11](#h11--deferred-items) | Deferred items (plus GH-15, GH-16) | 2 + 17 deferred | — | HD15 |
| | **Total** | **104 + 17 deferred** | | |

**Order and parallelism.** H0 first (it is free, and it shrinks what H1 has to gate). H1
next: after it, every later fix lands behind CI. H2 and H3 can run side by side; H3 is
deploy scripts and the VM, so it touches no file H2 does. H4 needs H4.0 (room in
`agent_loop.py`) before anything else in it. H5–H9 follow in that order, but H7, H8 and H9 are
independent of each other. H10 closes the documentation once the code it describes is true.
H11 runs whenever the product owner un-defers an item; MC-24 is recommended for the H4 slot.

**Sizes** in the tables: **S** — under half a day; **M** — up to two days; **L** — more,
or needs a design pass first.

---

## 4. Decisions needed

Each is the product owner's. The recommendation is what this plan assumes if no other
answer is given; the phase cannot finish without the answer.

| # | Decision | Recommendation | Blocks |
|---|---|---|---|
| **HD1** | Push the branch and turn on GitHub Actions | Push `roadmap-development-defect-fixes` now. CI only runs on a remote; until then H1 can be checked locally with `act` at best | H1 |
| **HD2** | Which webhook sources stay, and where their secrets live | Keep a source only when the tenant has configured its secret; store secrets per company, encrypted (after AU-24). A source with no secret answers 401 | H2.1 |
| **HD3** | One short-lived token for URLs and sockets | A signed token, ≤ 60 s, bound to the user, company and a path prefix, minted by `POST /api/v1/auth/url-token`. Used by artifact previews (FE-28), the SSE stream, and the `/stream/audio` and `/stream/video` handshakes (GW-04). Access tokens are refused in query strings | H2.3, H2.4 |
| **HD4** | Encryption-key rotation (AU-24) | Versioned ciphertext with an HKDF-derived key; one re-encryption script per environment; boot refuses the repository default outside development. Rotate before the first tenant stores a credential | H2.6 |
| **HD5** | Who owns a template (PO-23) | The one APP company (unique since LP-21). Only `app_admin` writes templates; tenants read and clone | H2.8 |
| **HD6** | Off-host backup target | A GCS bucket in `hirebuddha-production`, object versioning on, 90-day lifecycle; daily dumps | H3.1 |
| **HD7** | What a HITL rejection ends (GH-25) | The run, as `CANCELLED` with the reviewer's reason — no critic call, no retry. A timeout ends it `FAILED`. (Alternative: only the plan branch) | H4.1 |
| **HD8** | A company-level spend cap (GH-18) | `monthly_spend_cap_usd` per company, checked by `CreditGuard` at admission and by the breaker; empty means no cap | H4.6 |
| **HD9** | Inbound-call credit policy (VT-01, VT-08) | One admission rule for both directions: refuse on `free` below the floor; if the balance cannot be read, refuse. (Alternative: keep "never miss an inbound call", but say so in the product and emit a metric each time) | H5.1 |
| **HD10** | Azure Realtime (VT-02) | Remove it from the provider list until a customer needs it — it has never worked. (Alternative: fix the tuple and the PCM conversion) | H5.6 |
| **HD11** | Video (GW-10, GW-06, GW-13) | Delete `/stream/video`, the TURN settings and the Apache rule (GW-I10). (Alternative: declare `aiortc`, fix `video_gateway.py:207`, test end to end) | H6.4 |
| **HD12** | More than one API instance (GW-21) | Record "one instance" as a decision now; sticky sessions by `session_id` when a second is needed | H6.5 |
| **HD13** | DTMF and voice prosody (VT-13, VT-11) | Say DTMF is unsupported outside the mobile dialer (VT-I9); remove `speaking_rate` and `pitch` from the voice settings unless the current Gemini Live API accepts them | H5.7, H5.8 |
| **HD14** | Is a call a run (VT-21)? | Yes — every call opens its run at call start (today only tool use does), so calls appear in reports and traces. Critics and HITL stay off for voice, and the builder says so | H5.4 |
| **HD15** | Un-defer register 08 and 01 items | Un-defer MC-24 (High, small, loses schedules) and MC-06 (High, silent failures) now; leave the rest deferred | H11 |
| **HD16** | Version `/api/social-connections` (API-15) | Now, with the old path as an alias for one release | H8.1 |
| **HD17** | Per-tenant quotas (GH-03) | A per-company limit on runs started per minute, failing closed; tool-call quotas later | H4.8 |
| **HD18** | Fixture loading coupled to the entity schema (TS-17) | Accept and document it — it is what catches schema drift | H1.11 |

---

## 5. The phases

Each table lists the entries the phase closes, what is done, and how the fix is proven.
Every fix also follows [§6](#6-how-each-fix-is-worked).

### H0 — Clear the ground

No behaviour change. Deletions and moves only, in one or two commits. **Exit:** the
deleted paths are gone, nothing imports them, the full host suite and the frontend gates
pass.

| # | Ids | Work | Size | Proof |
|---|---|---|---|---|
| — | Re-verification and this plan | — | Every non-fixed entry checked against the code; registers 12, 13, 15, 17, 18, 19, 20 given status lines and status tables; stale entries in 01, 04, 05, 06, 07, 16 corrected. Unit suite on this machine: 1,833 passed, 6 failed — the 4 known Windows sandbox tests, the known chaos test, and `test_single_port_app` with Redis not running |
| H0.1 | TS-09, ON-11 | Delete the root `tests/` directory (four `__init__.py` files) | S | `git ls-files tests/` empty |
| H0.2 | TS-12 | Delete `backend/tests/phase9/` (two scripts, no tests) | S | Suite collects the same count |
| H0.3 | TS-13 | Keep one `MockLLMRouter` (`tests/harness/mock_llm.py`); point `tests/fixtures/llm_fixture.py` at it | S | Suite passes |
| H0.4 | ON-10 | Delete `src/ai/models.py`; import from `src.ai.orm.*` everywhere (`ExecutionRun`, `HierarchicalEntity` and the rest) | M | Grep finds no `src.ai.models` import; suite, type check and layout lint pass |
| H0.5 | ON-14 | Move `docs/phase1` … `docs/phase12` to `docs/history/` (ON-I8); fix links | S | Link check over `docs/current` |
| H0.6 | API-11 | Delete the `/api/v1/assets` shims (`main.py:134`, `:137`) — their table is gone (DM-10) | S | Route census: no `/assets` route |
| H0.7 | API-13 | Delete `GET /api/v1/auth/admin-only` | S | Route census |
| H0.8 | GW-09 | Drop the nginx-only `X-Accel-Buffering` header (`ai/router.py:362`); note in the Apache vhost that SSE paths must not get `mod_deflate` | S | — |

### H1 — Turn on the lights

After this phase, a red test blocks a merge. **Needs HD1.** **Exit:** a pull request runs
every gate below on GitHub, and the run is green; a deliberately broken test turns it red.

| # | Ids | Work | Size | Proof |
|---|---|---|---|---|
| H1.1 | IN-05, TS-02 | `.github/workflows/backend.yml`: Python 3.12, Postgres 16 + pgvector and Redis 7 as services, `poetry install`, `alembic upgrade head`, then unit + integration + parity (`--ignore=tests/e2e`). Docker-image tests keep their own marker and run in a separate job that builds the images | M | Green run on the branch; red on a planted failure |
| H1.2 | IN-18, TS-03 | Same workflow: `scripts/lint_ai_layout.py`, `tests/unit/test_typecheck.py`, ruff | S | Planted violation fails the job |
| H1.3 | FE-03, TS-04, TS-08 | `frontend`: a `test` script (`vitest run`, `jsdom`), drop the `*.test.ts(x)` exclude in `tsconfig.json` and fix what then fails to compile (`useExecutionEvents.test.ts`'s `_INITIAL`), and `.github/workflows/frontend.yml`: `npm ci`, lint, `tsc --noEmit`, `npm test`, `vite build` | M | Both test files run in CI |
| H1.4 | TS-05 | `REQUIRE_DB=1` turns the integration, e2e and parity fixtures' `pytest.skip()` into `pytest.fail()`; CI sets it | S | CI with Postgres stopped fails |
| H1.5 | TS-06 | `MockLLMRouter` raises on an unmocked call unless a test opts into stub mode | M | A test that reaches an unmocked LLM fails; fix the tests this exposes |
| H1.6 | TS-10, TS-11, TS-14, TS-15 | Remove the `kpi` and `needs_redis` markers, register `integration`, add `--strict-markers` | S | A typo'd marker fails collection |
| H1.7 | TS-16 | The parity fixtures delete the `parity-*` companies they create (the e2e `_e2e_cleanup` pattern) | S | Row counts unchanged after a parity run |
| H1.8 | IN-23 | `setup_tracing` attaches the OTLP exporter only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set and honours `OTEL_SDK_DISABLED`; export timeout ≤ 2 s | S | A unit run and an API reload print no exporter retries |
| H1.9 | — | Make the known failures pass or carry a reason: `chaos/test_feature_flags_table_unavailable::test_pool_exhaustion_falls_through_to_default`, and the two local-only `test_cost_attribution` failures (they collide with the registry seed). The four Windows sandbox tests pass on Linux | M | The CI baseline has zero known failures |
| H1.10 | — | Secret scan (gitleaks) in CI — closes IN-13 in H3.9 | S | A planted fake key fails the job |
| H1.11 | TS-17 | Per HD18: document the coupling in `19-testing.md`; mark accepted | S | — |

### H2 — Close the open doors

**Needs HD2–HD5.** Can run alongside H3. **Exit:** every request that creates work or
reads tenant data is authenticated; no long-lived token appears in a URL; no secret is
stored in plaintext or under a public key.

| # | Ids | Work | Size | Proof |
|---|---|---|---|---|
| H2.1 | **GW-01, API-03** | Implement each strategy's signature check in `gateway/webhook_inbound.py` — GitHub and Facebook/Instagram `X-Hub-Signature-256`, Twilio `X-Twilio-Signature`, LinkedIn, TikTok, X, YouTube WebSub; email, CRM and generic sources sign with a per-integration secret (GW-I4). A missing secret or a failed check is **401 and no enqueue**, with a `gateway.webhook.signature_failed` event. The webhook URL names the integration, so the right company's secret is used | L | Per provider: a real signed sample passes, a tampered body and an unsigned request are refused, nothing is enqueued (unit + `test_single_port_app`) |
| H2.2 | GW-03 | Deduplicate on the provider's delivery id (`X-GitHub-Delivery`, `I-Twilio-Idempotency-Token`, …; else SHA-256 of the body): Redis `SET NX EX 86400` before the enqueue. A repeat answers 200 `duplicate` | M | The same delivery twice → one job |
| H2.3 | FE-28 | Per HD3: the URL-token endpoint; `authedApiUrl` and `services/events.ts` mint one per use; `get_current_user_from_query` accepts only URL tokens scoped to the requested path | M | No access token in any request URL (browser network log); an access token in `?token=` is refused |
| H2.4 | GW-04 | `/stream/audio` and `/stream/video` verify a stream token (HD3) before resolving an agent; close `4401` otherwise. The Twilio/Tata streams accept only a session that exists, is fresh and is not already connected | M | Handshake without a token, with a foreign company's token, or replayed → closed |
| H2.5 | GW-17 | `resolve_agent_for_client` (`gateway/dispatcher.py:91`) uses an explicit per-company binding (the voice-enabled default agent) and refuses ambiguity with an error that names the fix | S | Two agents, no binding → refused; with a binding → that agent, every time |
| H2.6 | AU-24 | Per HD4: versioned AES-GCM with an HKDF-derived key in `common/security.py`; legacy ciphertext still decrypts; `scripts/rotate_encryption_key.py` re-encrypts every encrypted column (found by census); settings validation refuses the default key outside development | M | Round trip old → new; boot with the default and `ENVIRONMENT=production` fails |
| H2.7 | AU-25 | Encrypt `client_secret` and every other secret key in `social_connections.oauth_metadata` on write; a migration encrypts existing rows; no response returns it | M | Stored row has no plaintext secret; the refresh path still works |
| H2.8 | PO-23 | Per HD5: templates belong to the APP company (migration); `update_entity`/`delete_entity` refuse a template unless `app_admin`; `POST /ai/templates` works | M | A tenant's PUT/DELETE on a template → 403; template create → 201 |

### H3 — Keep the data, harden the host

**Needs HD6 and access to the VM.** Deploy scripts and configuration only. **Exit:** a
daily backup exists off the host and has been restored; the host exposes only 22, 80 and
443; nothing runs as root with a reloader.

| # | Ids | Work | Size | Proof |
|---|---|---|---|---|
| H3.1 | **IN-02, IN-01** | `db_backup.sh` derives its paths from its own location; daily at 02:00; copies each dump to the HD6 bucket and verifies size and checksum; keeps 7 days locally; non-zero exit and a log line on any failure | M | A dump in the bucket from the VM; a forced failure is visible |
| H3.2 | IN-03 | `deploy/backup/restore_test.sh`, weekly: restore the newest dump into a scratch database, check `alembic_version` is head and row counts are plausible, drop it | M | First successful restore recorded in the runbook |
| H3.3 | IN-04 | Postgres and Redis volumes become `external: true` (created by the setup script), so `docker compose down -v` cannot delete them | S | `down -v` leaves the data |
| H3.4 | IN-06 | Dockerfile: a non-root user, no `--reload`, `--proxy-headers`; `start_services.sh --prod` starts without `--reload`, and the VM setup uses it | S | Container runs as uid ≠ 0; the VM process has no reloader |
| H3.5 | IN-07 | Remove `uploads` from the security `LocationMatch` (or move the mount under `/artifact/`) | S | A profile picture loads through Apache |
| H3.6 | IN-08 | `deploy/firewall/setup_ufw.sh` (allow 22, 80, 443); compose binds 5433 and 6379 to `127.0.0.1`; Redis `requirepass`, carried in `REDIS_URL` (SA-05 keeps it) | M | External scan shows three open ports; the stack runs with the Redis password |
| H3.7 | IN-09 | `deploy/logrotate/hirebuddha`: daily, 14 kept, compressed, `copytruncate`; installed by the setup script | S | `logrotate -d` clean |
| H3.8 | IN-11 | `stop_services.sh` stops only this checkout's processes (pid files, or the full command line of `uvicorn src.main:app` and this repo's Vite) | S | Another uvicorn on the host survives |
| H3.9 | IN-13 | Closed by the CI secret scan (H1.10) and a pre-commit hook | S | — |
| H3.10 | IN-14 | `npm ci` without `--legacy-peer-deps` in `setup_production_vm.sh` | S | Clean install on the VM |
| H3.11 | IN-15 | Re-check which vhosts remain after the single-port merge; one certificate per hostname or an explicit SAN list in `setup_apache.sh`; renewal in the runbook | S | `openssl s_client` per hostname |
| H3.12 | IN-19 | `extra_hosts: host.docker.internal:host-gateway`; Grafana on 3001 | S | The observability stack scrapes the API on Linux |
| H3.13 | IN-20 | The worker exposes Prometheus metrics (jobs, durations, failures, queue depth) on its own port; added to `prometheus.yml` | M | Metrics visible for both workers |
| H3.14 | IN-21 | Release tags, a built frontend artefact (with SA-I1), and a rollback runbook that says when to run a migration's downgrade | M | One rehearsed rollback |

### H4 — Governance and HITL that hold

**Needs HD7, HD8, HD17.** **Exit:** a reviewer's answer is final; a pending approval holds no
worker; every gate that fails says so.

| # | Ids | Work | Size | Proof |
|---|---|---|---|---|
| H4.0 | IN-17, ON-09 | Make room: move run finalisation and suspend/resume out of `core/agent_loop.py` into their own modules until it has ≥ 200 lines of headroom. No behaviour change | M | Parity goldens and the kernel unit tests unchanged; layout lint passes |
| H4.1 | GH-25, AK-08 | Typed `HITLRejected` and `HITLTimeout` from `governance_service.py`; the executor reports a `blocked` step; the observer's outcome becomes `blocked`, so `state.blockers` finally has a producer (AK-08); the loop ends the run per HD7 with no critic call and no retry | M | The live GH-25 scenario: one approval request, run `CANCELLED` with the reason; the supervisor prompt shows the blocker |
| H4.2 | GH-07 (PO-20) | Park instead of wait (GH-I3): on a HITL checkpoint the run snapshots, goes `PAUSED` and returns its worker — the `WAITING_ON_CHILDREN` path; the approval endpoint enqueues the resume; `sweep_stuck_runs` times out a `PAUSED` run past its deadline through the H4.1 path. The credit hold persists | L | Ten pending approvals on a two-slot worker: other runs still run; approve → resumes at the same step |
| H4.3 | GH-08 | `COST_THRESHOLD` is checked before a step against the run's cost plus the step's estimate (P8.11's costing), so the human is asked before the line is crossed; the after-step check stays as a backstop | S | A step estimated across the threshold asks first |
| H4.4 | GH-09, GH-10 | `hitl_checkpoints` validated when the entity is saved (422 naming the checkpoint); `CUSTOM` accepts `step_count` and `cost` with `> >= < <= ==` joined by `and`/`or`, and nothing else; the builder's help text says so. A checkpoint that cannot be evaluated at run time asks the human and writes a trace event | M | A typo → 422; a legacy invalid checkpoint → asks, with the event |
| H4.5 | GH-05 | An unpriced tool writes a `usage_logs` row with source `missing` and a `tool.cost.missing` event on **every** call (no warn-once); the registry contract test fails on a non-free tool without a price, and free tools say `cost: 0` explicitly | S | Contract test red on an unpriced tool |
| H4.6 | GH-18 | Per HD8 | M | Cap reached → admission refused, running runs stop at the breaker |
| H4.7 | GH-21 | Every gate's failure path emits `gate.failed{gate=…}` (GH-I2); `RedisRateLimiter` defaults to failing closed; a test lists every gate and its failure mode, and a fail-open gate must name its decision | M | The gate inventory test |
| H4.8 | GH-03 | Per HD17 (GH-I10) | S | Burst over the limit → 429 |
| — | MC-24 | Recommended here if un-deferred (HD15); see H11 | S | — |

### H5 — Voice and messaging

**Needs HD9, HD10, HD13, HD14.** Money first, then the features that do not work. **Exit:** a
call cannot start on an empty wallet, is billed from the provider's numbers, and every
voice and messaging path either works or is gone.

| # | Ids | Work | Size | Proof |
|---|---|---|---|---|
| H5.1 | **VT-01**, VT-08 | One admission function for calls (VT-I10), used at both inbound checkpoints and outbound; reads `free` (net of other runs' holds), not `total_available`; behaviour per HD9; a metric each time | M | Empty wallet → inbound refused at the webhook; balance read failure → per HD9 |
| H5.2 | VT-05 | Bill from the Gemini Live session's `usage_metadata` (tokens by modality); fall back to per-direction speech durations, not the whole call, only when the provider sends none (VT-I1) | M | A recorded session's bill equals its usage metadata |
| H5.3 | VT-09, VT-10 | The campaign executor enforces `max_calls_per_hour` (a sliding window per campaign) and re-dials a failed or unanswered `CampaignCall` up to `max_retries` with backoff (VT-I2) | M | Executor tests with a fake dialler |
| H5.4 | VT-21 | Per HD14: the call's run opens at call start; the tool-call run (TL-20) becomes that run | M | A call appears in the run reports and the trace viewer |
| H5.5 | VT-03 | Pass `service_metadata` from the agent's resolved text integration to `GeminiTextServiceFactory.get_service` | S | Unit with a fake factory; one live WhatsApp sandbox reply |
| H5.6 | VT-02 | Per HD10 | S/M | — |
| H5.7 | VT-11, VT-12 | One Gemini Live config builder; prosody per HD13 | S | — |
| H5.8 | VT-13 | Per HD13 (VT-I9) | S | — |
| H5.9 | VT-15 | One live Smartflo call to confirm the key; flip the default; the two error replies use the setting | S | Live check recorded |
| H5.10 | VT-16 | Invalidate the agent cache when the entity changes — a Redis channel every API process listens on (VT-I3) | S | Edit → the next call uses the new prompt |
| H5.11 | VT-17 | Pad mu-law with `0xFF` | S | Unit |

### H6 — Real-time transport

**Needs HD11, HD12.** **Exit:** a run page survives a reconnect without polling; the live
socket surface is exactly what the product uses.

| # | Ids | Work | Size | Proof |
|---|---|---|---|---|
| H6.1 | GW-19 (PO-19) | Terminal events carry `terminal: true`; the SSE generator parses the frame and stops on the field (SA-I8), not on a substring | S | A tool result containing `"status": "COMPLETED"` does not end the stream |
| H6.2 | GW-18 | Run events go to a Redis stream per run (`XADD … MAXLEN ~ 1000`); SSE frames carry `id:`; `Last-Event-ID` replays (GW-I7); the frontend drops the 3-second poll except as a fallback when the stream errors | M | Disconnect mid-run, reconnect: no gap |
| H6.3 | GW-02 | The remainder: a per-company cap on concurrent voice sockets and a per-IP handshake rate; webhooks limited per source and company instead of exempt | S | Over the cap → refused |
| H6.4 | GW-10, GW-06, GW-13 | Per HD11 | S/L | — |
| H6.5 | GW-21 | Per HD12: the decision recorded in `13-gateway-and-realtime.md`; health reports the instance id. Then mark accepted | S | — |

### H7 — Feature flags you can trust

**Exit:** a flag's value can be set everywhere the documentation says, changes reach every
process at once, and the page says where a value came from.

| # | Ids | Work | Size | Proof |
|---|---|---|---|---|
| H7.1 | GH-13 | `get_float` reads `AI_FLAG_<KEY>` between the global row and `NUMERIC_DEFAULTS` (GH-I9) | S | Unit |
| H7.2 | GH-14 | The admin flag endpoint writes through `FeatureFlags.set`, which publishes the invalidation; an `invalidate` admin endpoint for manual SQL, named in the runbook | S | A change from the page is seen by a worker within a second |
| H7.3 | GH-20 | `FeatureFlags.explain()` returns the value and the tier that produced it; the flags page shows both (GH-I7) | M | Page shows "company row" vs "env" vs "default" |

### H8 — One consistent API surface

**Needs HD16.** **Exit:** an integrator can page every list the same way and read the real
route table.

| # | Ids | Work | Size | Proof |
|---|---|---|---|---|
| H8.1 | API-15 | `/api/v1/social-connections`, old path an alias for one release (API-I7); frontend moved | S | Both paths answer; the old one logs a deprecation |
| H8.2 | API-16 | One page envelope (`items`, `next_cursor`, `limit` ≤ 200) on integrations (company-scoped for `app_admin` too), entities, executions and artifacts (API-I3); frontend follows | L | Lists past one page work |
| H8.3 | API-17 | A route census test that writes the full path table into `17-api-reference.md` and fails on drift (API-I1) | S | Adding a route without updating the doc fails |
| H8.4 | API-18 | `DELETE /ai/entities/{id}` documented as a soft delete in OpenAPI, returns the status and `deleted_at`; `include_deleted` for admins (API-I8) | S | — |
| H8.5 | API-19 | OpenAPI summaries say what each tools endpoint returns and who may call it; rename if the frontend allows | S | — |

### H9 — Frontend data layer

| # | Ids | Work | Size | Proof |
|---|---|---|---|---|
| H9.1 | FE-21 | `QueryClientProvider` at the root; move `PhonePool`, the `EntityFlow` Hierarchy tab, `AppAdminReports`, `TenantAdminReports`, `PlatformManagement` and `ToolManagement` to queries; mutations invalidate their keys (FE-I3) | L | `PhonePool` mounts with one request per resource, cached on return; vitest for the hooks |

### H10 — Documentation and onboarding

After H1 and H4, so the documents describe what is true. **Exit:** a new developer who
follows `20-onboarding-and-glossary.md` exactly gets a stack that can run an agent, and
nothing in it describes code that does not exist.

| # | Ids | Work | Size |
|---|---|---|---|
| H10.1 | ON-01 | Add `seed_integration_registry.py` and `seed_sandbox_sku` to the setup sequence (or one setup script, ON-I1) | S |
| H10.2 | ON-03 | Verification checks `GET /api/v1/health` reports `models: ok` and runs one agent | S |
| H10.3 | ON-06 | Replace the first-change exercise with one on tool grants (`ToolAccess`) (ON-I3) | S |
| H10.4 | ON-07, ON-08 | Describe the gate inventory (H4.7) and the real CI (H1) | S |
| H10.5 | ON-15, ON-16, ON-17 | Glossary: mark deprecated reasoning modes; generate the flag counts from the census; `Viewport` marked not wired | S |
| H10.6 | ON-18 | A "known gaps" line at the end of every document's §1, linking its register (ON-I5) | S |
| H10.7 | TS-18 | Fix the three drifted claims in `19-testing.md` and `ONBOARDING.md` | S |
| H10.8 | API-20 | `AI_MODEL_CREDENTIALS_GUIDE.md` uses `/api/v1/config/...` | S |

### H11 — Deferred items

Each waits on HD15; nothing here is started without the product owner's word.

| Ids | What | Size | Note |
|---|---|---|---|
| **MC-24** | Scheduled CORTEX resume: use `ctx['redis']` directly, commit the run before enqueueing, clear `next_resume_at` only after the enqueue succeeds (`ai/core/arq_jobs.py:745–750`) | S | **Recommended now** — every scheduled resume loses its schedule today |
| **MC-06** | Count each domain's retrieval failure and put it on the run trace; `[]` from an error ≠ `[]` from an empty tree | M | **Recommended now**; package change (port to `hb-cortex-memory`) |
| MC-09 | Check the `cortex_router.py` `recurse()` path enqueues | S | |
| MC-10 | Foreign keys from CORTEX tables to host tables | M | Package change |
| MC-11, MC-13 | Vector dimension from one setting; the pgvector index in the model | S | Package change |
| MC-14 | One chunker | M | |
| MC-15, MC-16, MC-19, MC-23 | Viewport `max_chars`; invariant 1 in development; one place for internal keys; episodes listed once | S each | |
| GH-15, GH-16 | Delete or wire `memory_v2.canonical` and the three `memory.*` flags; shrink `KNOWN_UNREAD` in `test_feature_flag_census.py` | S | Follows the MC decisions |
| PO-03, PO-08, PO-21, PO-22 | Onboarding push, `DB_RECORDS`, "agent" naming, costing vs billing reports | S–M | PO-19 and PO-20 are fixed by H6.1 and H4.2 |

---

## 6. How each fix is worked

As [`SESSION-HANDOFF.md` §5](SESSION-HANDOFF.md#5-how-a-defect-is-worked), with two additions
once H1 lands:

1. Read the register entry and the code it cites; re-verify the claim (line numbers drift).
2. Reproduce it — a script against the local database or a live call over reasoning alone.
3. Fix at the root, in one place.
4. Write a test that fails on the old code (run it against `git show HEAD:<file>`).
5. Verify live where the defect is observable at runtime.
6. Run the gates locally; **after H1, the pull request's CI run is the gate of record.**
7. Update the area's design document and the register's status line and status table;
   record any new defect the fix exposes as a new entry, unfixed.
8. Commit per defect: `fix(<area>): <what is now true> (<ID>)`; add a row to the
   [progress log](#progress-log). **After H1, push and let CI run before the next defect.**

A phase is done when every entry in it is fixed, accepted by a recorded decision, or found
invalid — and its exit line holds.

---

## Progress log

Columns: phase · ids · commit · evidence. Updated as each fix lands.

| Phase | Ids | Commit | Evidence |
|---|---|---|---|
| H0.1 | TS-09, ON-11 | `c9edbfd` | The empty root `tests/` tree deleted |
| H0.2 | TS-12 | `ebdb54b` | `backend/tests/phase9/` deleted; the collected suite unchanged (1,844) |
| H0.3 | TS-13 | `d3497d6` | `test_one_mock_llm_router.py` (two definitions on the old code) |
| H0.4 | ON-10 | `753589f` | 67 importers moved to `src.ai.orm`; `test_models_shim_is_gone`; layout lint no longer tolerates `models.py`. Unit 1,835 + the 6 known failures |
| H0.5 | ON-14 | `b9d3591` | `docs/phase*` → `docs/history/` as pure renames; 35 references rewritten, all resolve |
| H0.6 | API-11 | `8508656` | `test_retired_routes_are_gone` fails on the old `main.py`; e2e asset tests moved to `/api/v1/artifacts` |
| H0.7 | API-13 | `9f60567` | Same test, fails on the old router; e2e role-guard tests probe `GET /config/task-defaults` |
| H0.8 | GW-09 | `01fa369` | `SSE_HEADERS` = `no-cache, no-transform`; `test_sse_headers.py`. Not checked behind a live Apache |
| **H0 done** | 9 entries | — | Local Docker's data was found gone on 2026-10-07 (a new data disk); e2e and integration runs wait on a rebuilt database |
