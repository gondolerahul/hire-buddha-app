# Merge Readiness and Production Rollout

> **What this document is:** the risks of merging `roadmap-development-defect-fixes` into
> `main`, the gates to clear before merging, and the plan for applying the change to the
> production Ubuntu VM on GCP.
> **Written:** 2026-10-09, at branch tip `64aecc9` (pushed), against `origin/main` at
> `9896b8b`.
> **Status:** **not ready to deploy.** Merging is mechanically safe (a fast-forward), but
> the change cannot go to production until the gates in [§4](#4-gates-before-merging) hold.
> Nothing in this document has been executed; it is a plan.

---

## Contents

1. [Verdict](#1-verdict)
2. [The change at a glance](#2-the-change-at-a-glance)
3. [Risks](#3-risks)
4. [Gates before merging](#4-gates-before-merging)
5. [Production rollout plan (GCP Ubuntu VM)](#5-production-rollout-plan-gcp-ubuntu-vm)
6. [Rollback](#6-rollback)
7. [Appendix A — configuration changes](#appendix-a--configuration-changes)
8. [Appendix B — what was never verified live](#appendix-b--what-was-never-verified-live)

---

## 1. Verdict

| Question | Answer |
|---|---|
| Will the merge conflict? | **No.** `main` has no commits since the branch was cut at `9896b8b`; the merge is a fast-forward |
| Is the code tested? | On one Windows development machine: unit tier 2,133 passed / 0 failed; integration + parity 445 passed / 0 failed; frontend lint, type check, vitest and build clean. **Never in CI, never on Linux** |
| Can it be deployed as-is? | **No.** It needs a tested backup, a rehearsal on a copy of production, new configuration, a key rotation, a second worker, sandbox images, new system packages, and every external webhook and telephony sender re-pointed |
| Can it be rolled back? | **Only by restoring a disk snapshot or a database dump.** Several migrations drop tables or rewrite data; `git checkout` plus `alembic downgrade` is not a reliable way back |

**Recommendation:** merge to `main` only after the gates in §4 are met, and deploy in one
maintenance window that follows a full rehearsal on a clone of the production VM (§5.2).

---

## 2. The change at a glance

| Measure | Value |
|---|---|
| Commits | 345 (branch ahead of `main`; 0 behind) |
| Files | 1,190 changed — +74,782 / −39,037 lines |
| Files deleted | 110, of them 63 under `backend/src` or `frontend/src` |
| Alembic migrations | 37 new; 3 existing ones edited (`m0b1e0d1a100`, `m0b1e0d1a200`, `p12_retire_reasoning_modes`); 1 renamed (same revision id) |
| Python | `^3.11` → `^3.12` |
| New Python dependencies | `aiortc` (+ PyAV), `weasyprint`, `markdown`, `ddgs`, `playwright`, `anthropic`; `stripe` removed |
| Frontend dependencies | `@tanstack/react-query` added, `@react-three/*` removed; `package-lock.json` largely rewritten |
| Processes | API on **8000 only** (gateway 8001 and voice 8002 retired); **two** Arq workers (main + `children` queue) |
| Defects closed | Registers 02–07, 09–11, 14–17 and the tool-layer audit fully closed; see each register |

---

## 3. Risks

Severity: **H** — can cause an outage, data loss or wrong billing; **M** — breaks a feature
or an integration; **L** — operational friction. "Plan" points at the step that handles it.

### 3.1 Data and migrations

| # | Risk | Sev | Mitigation | Plan |
|---|---|---|---|---|
| R1 | **No proven backup.** Backups are monthly, on the database's own disk, written to a stale path; no restore has ever been tested (IN-01…IN-03 open) | H | GCE disk snapshot plus an off-host `pg_dump` taken and **restored** before the window | §5.3 |
| R2 | **Upgrades drop tables** — e.g. `assets` (DM-10), `source_trust_scores` (P7), the legacy memory tables (MC-05, MC-18). Their data is gone after `upgrade head` | H | Confirm nothing in production still needs them; keep the pre-upgrade dump | §5.2, §5.3 |
| R3 | **Irreversible rewrites:** `timestamp` → `timestamptz` (DM-12), `json` → `jsonb` (DM-13), run-log composite keys (DM-09), lower-cased emails (AU-26), hashed refresh tokens (AU-10), sealed social secrets (AU-25) | H | Rollback is restore-only (§6) | §6 |
| R4 | **DM-12 assumes every stored timestamp is UTC.** Three code paths were found writing local time; rows written by them in IST shift by 5:30 | M | On the rehearsal clone, compare a sample of `created_at` values before and after against known events | §5.2 |
| R5 | **AU-26 stops the upgrade on purpose** if two accounts differ only in email case | M | Run the clash query on production before the window; merge or rename the accounts | §5.1 |
| R6 | **Three already-applied migrations were edited.** If production applied the old versions, the edits never run there and its schema drifts from a fresh build | M | Compare the rehearsal clone's schema after upgrade with a fresh `alembic upgrade head` (the schema-census test does this on a scratch DB) | §5.2 |
| R7 | **Production's `alembic_version` is unknown** relative to this chain (branches, stamps, hand-applied scripts) | M | Record `alembic current` on production first; rehearse from exactly that state | §5.1 |
| R8 | **Long or locking migrations.** `json`→`jsonb` and `timestamptz` rewrite whole tables under lock; duration on production volumes is unmeasured | M | Time every migration on the rehearsal clone; size the window from it | §5.2 |

### 3.2 Secrets and configuration

| # | Risk | Sev | Mitigation | Plan |
|---|---|---|---|---|
| R9 | **`ENCRYPTION_MASTER_KEY` is now required** (≥ 32 random characters) — the API refuses to start without it (AU-24) | H | Generate and store it before the window | §5.1 |
| R10 | **Stored credentials need re-encrypting.** The key is now HKDF-derived (`v2:` ciphertexts). If production ran on `main`'s default key (`your-default-dev-key-must-be-32-bytes`) or any other, every model, telephony, email and social credential must be rotated with `scripts/rotate_encryption_key.py`, or the platform cannot call any provider | H | Rotation with `OLD_ENCRYPTION_MASTER_KEY`, dry run then `--apply`, rehearsed | §5.4 step 6 |
| R11 | **AU-25's migration encrypts social secrets during `alembic upgrade`** with the configured key — the key must be set *before* migrating | H | Order in §5.4 | §5.4 |
| R12 | **Tracing stops** unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set (IN-23 removed the `localhost:4317` default) | L | Set it if Jaeger/Tempo runs on the VM | App. A |
| R13 | **`INTERNAL_TOKEN` empty or a placeholder disables `POST /internal/event`** (503) | M | Set a real token if any internal service posts events | App. A |
| R14 | **New default limits may refuse real traffic:** 60 runs started per minute per company (`RUNS_STARTED_PER_MINUTE`), 20 live voice/video sessions per company, 200 REST requests/min per IP, 300 webhook deliveries/min per endpoint, 30 WebSocket handshakes/min per IP | M | Check against production peaks; set the variables before go-live | App. A |
| R15 | **Account emails need SMTP.** New sign-ups must verify their email (AU-08) and password reset is by email (AU-06); without a working system SMTP integration nobody new can sign in. (Existing users are marked verified by `au08_verify_existing_users`.) `EMAIL_LINKS_IN_LOG` must stay `false` in production | H | Configure and test SMTP; set `FRONTEND_URL` to the production SPA origin | §5.4, §5.5 |

### 3.3 Topology, host and dependencies

| # | Risk | Sev | Mitigation | Plan |
|---|---|---|---|---|
| R16 | **Python 3.12 is required.** `main` declared `^3.11`; a VM still on 3.11 cannot install the branch | H | `setup_production_vm.sh` installs 3.12; rebuild the venv | §5.4 step 3 |
| R17 | **New system packages:** `weasyprint` needs Pango/Cairo; `playwright` needs a browser download and its OS libraries; `aiortc`/PyAV need wheels or FFmpeg libraries | M | Install on the rehearsal clone first; record the exact `apt` list | §5.2 |
| R18 | **A second worker is required** (SA-07). A host that starts only `WorkerSettings` leaves every child run waiting forever; health reports `down` | H | `start_services.sh` starts both; verify in health | §5.5 |
| R19 | **The container sandbox is the default runtime** (TL-01). Without Docker access for the app user and the `hb-sandbox:local` and `hb-egress-proxy:local` images, every code, terminal, browser and synthesized tool fails | H | Build both images on the VM | §5.4 step 5 |
| R20 | **Ports 8001 and 8002 are gone.** Apache vhosts, `STREAMING_HOST`, Twilio/Tata webhook and media URLs and the mobile app must all point at the API on 8000 through `gateway.`/`api.` | H | Updated vhosts in `deploy/apache/`; `streaming.` vhost deleted | §5.4 step 7, §5.6 |
| R21 | **Deploy scripts changed and were never run on Linux** in this cycle (`start_services.sh`, `stop_services.sh`, `setup_production_vm.sh`, `setup_apache.sh`) | M | Run them on the rehearsal clone | §5.2 |
| R22 | **The in-repo CORTEX copy is what runs.** `pyproject.toml` pins the published `hb-cortex-memory 0.1.0`, but `backend/cortex_memory/` has diverged (DM-14 column rename `metadata` → `edge_metadata`, MC-06, MC-21, MC-22). It wins only because the app runs from `backend/`. If the published wheel is ever imported instead, CORTEX fails against the migrated schema | M | Always start processes from `backend/`; port the package changes and republish before relying on the wheel | §4 |
| R23 | **The frontend runs as the Vite dev server** (`npm run dev`) in production and must be reinstalled (`npm ci`) for the new lockfile; `setup_production_vm.sh` still passes `--legacy-peer-deps` (IN-14) | L | `npm ci` in the window | §5.4 step 4 |
| R24 | **The host is unhardened:** no firewall (IN-08), root container with `--reload` (IN-06), no log rotation (IN-09). Not made worse by the merge, but the merge adds surface — e.g. worker metrics on 9101/9102 (bound to 127.0.0.1 by default) | M | Keep `WORKER_METRICS_ADDR=127.0.0.1`; schedule H3 | §4 |

### 3.4 Breaking changes for clients and integrations

| # | Risk | Sev | Mitigation | Plan |
|---|---|---|---|---|
| R25 | **Everyone is signed out** — refresh tokens are stored hashed and carry a token version (AU-10, AU-12) | L | Announce it | §5.1 |
| R26 | **Inbound webhooks must be re-registered.** `POST /webhook/inbound` now always answers 401; each source needs an endpoint (`POST /api/v1/webhook-endpoints`, secret shown once) and must deliver to `/webhook/inbound/{endpoint_id}` with its signature (GW-01). There is no UI for this yet | H | List every current webhook sender; create endpoints and update each provider | §5.6 |
| R27 | **Live sockets need a stream token** (GW-04); access tokens in a query string are refused (FE-28). Any client using the old `/stream/audio` or `/stream/video` handshake — including the mobile app, if it does — breaks | H | Check the mobile app and any embedded web client before go-live | §4, §5.6 |
| R28 | **API contract changes:** four lists return `{items, next_cursor, limit}` instead of an array (API-16); `/ai/tools`, `/api/v1/assets`, `/auth/admin-only` deleted; `/api/social-connections` is a one-release alias of `/api/v1/social-connections`; an unknown entity-config key is a 422 (PO-09); only `app_admin` writes templates (PO-23) | M | Inventory external API callers (scripts, partners, mobile) | §4 |

### 3.5 Behaviour and money

| # | Risk | Sev | Mitigation | Plan |
|---|---|---|---|---|
| R29 | **Inbound calls are refused** when free credit is below the floor or the balance cannot be read (VT-01, HD9) — they were never refused before | H | Check every telephony tenant's balance before go-live; tell customers | §5.1 |
| R30 | **Billing is computed differently:** credit holds while a run is in flight, a breaker that stops runs, the monthly spend cap, voice billed from provider tokens (VT-05), browser audio billed (VT-22), `$0` "missing" rows for unpriced tools | H | Compare a day of billing before/after on the rehearsal clone where possible; watch the first days | §5.7 |
| R31 | **HITL changed:** a rejection cancels the run, a timeout fails it, and waiting runs are parked `PAUSED` and resumed by the `resume_paused_run` job (GH-07, GH-25). Approvals pending at deploy time were made by the old code | M | Drain or resolve pending approvals before the window | §5.4 step 1 |
| R32 | **Gates fail closed** (GH-21): an outage of Redis or the database now refuses requests instead of silently passing | M | Expected; watch `gate.failed` events | §5.7 |
| R33 | **The first cron runs after deploy act on every company** — billing renewal, Razorpay reconciliation, stuck-run sweep, dreaming | M | Deploy outside the 00:00 and 01:30 UTC billing crons; watch the first run | §5.4, §5.7 |

### 3.6 Process

| # | Risk | Sev | Mitigation | Plan |
|---|---|---|---|---|
| R34 | **No CI** (IN-05). Nothing gates the merge; the test evidence is from one Windows machine | H | At minimum run the full suites on the rehearsal clone (Linux) | §4, §5.2 |
| R35 | **Unreviewable size.** 345 commits from several sessions; no human can review it as one change | M | Review by area using the registers and the progress log; rely on the rehearsal | §4 |
| R36 | **No rollback runbook** (IN-21): no release tag, no build artefact | H | Tag `main` before and after; snapshot-based rollback (§6) | §5.3, §6 |
| R37 | **Unverified integrations** — see [Appendix B](#appendix-b--what-was-never-verified-live) | M | Smoke-test each one in the window or immediately after | §5.5 |

---

## 4. Gates before merging

Merge to `main` only when every **must** holds.

| # | Gate | Must / should |
|---|---|---|
| G1 | The rehearsal in §5.2 completed end to end on a clone of the production VM, with every migration timed and the smoke checks in §5.5 green | **Must** |
| G2 | A backup taken from production has been **restored** successfully somewhere other than the VM (§5.3) | **Must** |
| G3 | The full backend suites passed **on Linux** (the rehearsal clone): `REQUIRE_DB=1 pytest tests -m "not (e2e or docker)"`, plus the frontend gates | **Must** |
| G4 | An owner and a maintenance window are agreed; tenants with telephony and webhook integrations are told (R25, R26, R29) | **Must** |
| G5 | The external callers are inventoried: every webhook sender, telephony number, the mobile app version in use, any script or partner calling the API (R26–R28) | **Must** |
| G6 | `ENCRYPTION_MASTER_KEY` generated and stored in the team's secret store; SMTP integration ready (R9, R15) | **Must** |
| G7 | CI on the branch (H1.1/H1.2) — or an explicit decision to merge without it | Should |
| G8 | CORTEX package changes ported to `hb-cortex-memory` (R22) | Should |
| G9 | Release tags: `pre-defect-fixes` on current `main`, `defect-fixes-1` on the merged tip | Should |

---

## 5. Production rollout plan (GCP Ubuntu VM)

Assumptions, to be confirmed in §5.1: one Ubuntu 22.04/24.04 GCE VM; the checkout at
`~/hire-buddha-app`; Postgres (pgvector, host port 5433) and Redis in Docker via
`backend/docker-compose.yml`; API, both workers and the Vite frontend as `nohup` processes
from `start_services.sh`; Apache with Let's Encrypt in front. Placeholders: `<PROJECT>`,
`<ZONE>`, `<VM>`, `<DISK>`, `<BUCKET>`.

### 5.1 Preparation (days before)

1. **Record the production state:**

   ```bash
   cd ~/hire-buddha-app && git rev-parse HEAD && python3 --version && docker ps --format '{{.Names}} {{.Image}}'
   ```

   ```bash
   cd ~/hire-buddha-app/backend && .venv/bin/alembic current
   ```

   ```bash
   gcloud compute instances describe <VM> --zone <ZONE> --format="value(disks[].source)"
   ```

   Note which disk holds the Docker volumes (boot disk or a data disk); both must be in
   every snapshot.

2. **Check for blockers in the data:**

   ```bash
   docker exec hirebuddha-db psql -U postgres -d hirebuddha -c "SELECT lower(email), count(*) FROM users GROUP BY 1 HAVING count(*) > 1;"
   ```

   Any row stops AU-26 (R5) — resolve with the account owners first. Also list pending
   approvals and running runs (R31):

   ```bash
   docker exec hirebuddha-db psql -U postgres -d hirebuddha -c "SELECT status, count(*) FROM execution_runs WHERE status IN ('PENDING','RUNNING','PAUSED','WAITING_ON_CHILDREN') GROUP BY 1;"
   ```

3. **Find the current encryption key.** Read `ENCRYPTION_MASTER_KEY` from the VM's
   `backend/.env`; if it is absent, production has been using `main`'s default,
   `your-default-dev-key-must-be-32-bytes`. That value becomes `OLD_ENCRYPTION_MASTER_KEY`
   in §5.4. Generate the new key and keep it in the secret store:

   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

4. **Inventory external callers** (G5): webhook sources and their URLs, Twilio/Tata number
   configuration (voice URL, status callback, media stream host), the mobile app's API and
   stream hosts, any cron or partner calling the REST API.

5. **Check telephony tenants' credit** (R29) and decide the limits in Appendix A.

6. **Announce:** maintenance window, sign-out of all users, webhook re-registration for
   affected tenants.

### 5.2 Rehearsal on a clone of production (required — G1)

Run the whole of §5.4–§5.5 on a copy of the production VM, never on production first.

1. **Snapshot and clone:**

   ```bash
   gcloud compute disks snapshot <DISK> --zone <ZONE> --snapshot-names hb-rehearsal-$(date +%Y%m%d)
   ```

   ```bash
   gcloud compute disks create hb-rehearsal-disk --zone <ZONE> --source-snapshot hb-rehearsal-$(date +%Y%m%d)
   ```

   ```bash
   gcloud compute instances create hb-rehearsal --zone <ZONE> --machine-type <same as prod> --disk name=hb-rehearsal-disk,boot=yes --no-address
   ```

   (Repeat the snapshot/disk steps for a separate data disk if there is one.)

2. **Isolate the clone before starting anything on it.** It holds production credentials,
   tenants and queued jobs. Without isolation it would charge cards (Razorpay
   reconciliation), send emails, dial campaign leads and answer webhooks:
   - no external IP (above) and a VPC firewall rule denying its egress except to package
     mirrors, Docker Hub and Google APIs needed for the install;
   - empty the Redis queue on the clone before the workers start
     (`redis-cli --scan --pattern 'arq:*' | xargs -r redis-cli DEL`);
   - do not change DNS.
3. **Run §5.4 exactly as written**, timing each step, and record:
   - the duration of `alembic upgrade head` per migration (`alembic upgrade +1` repeatedly
     gives per-step timings);
   - the rotation script's dry-run counts and its `--apply` result;
   - every `apt` package that had to be added (R17);
   - anything that differed from this plan — fix the plan, not the clone.
4. **Verify data** (R4, R6): compare a sample of timestamps with known events; compare the
   clone's schema with a fresh `alembic upgrade head` on an empty database (or run
   `tests/integration/test_schema_census.py` against it).
5. **Run the suites on Linux** (G3) from the clone's `backend/`:

   ```bash
   REQUIRE_DB=1 .venv/bin/python -m pytest tests -q -m "not (e2e or docker)"
   ```

   ```bash
   .venv/bin/python -m pytest tests -q -m docker
   ```

6. Run §5.5's checks that do not reach outside the clone. Then delete the clone.

### 5.3 Backup immediately before the window (G2)

1. Stop writes first (§5.4 step 1), then:

   ```bash
   docker exec hirebuddha-db pg_dump -U postgres -Fc hirebuddha > ~/hb-pre-merge-$(date +%Y%m%d-%H%M).dump
   ```

   ```bash
   gsutil cp ~/hb-pre-merge-*.dump gs://<BUCKET>/pre-merge/
   ```

   ```bash
   gcloud compute disks snapshot <DISK> --zone <ZONE> --snapshot-names hb-pre-merge-$(date +%Y%m%d-%H%M)
   ```

2. The dump must have been restored once before (G2) — `pg_restore` into a scratch
   database on another machine, check `alembic_version` and row counts of `companies`,
   `users`, `execution_runs`, `usage_logs`.
3. Tag the code: `git tag pre-defect-fixes <current prod sha> && git push origin pre-defect-fixes`.

### 5.4 The maintenance window

Expected length: the rehearsal's measured time plus 50%. Run as the app user from
`~/hire-buddha-app`.

1. **Stop traffic and work.** Put Apache in maintenance (or stop it), wait for running runs
   to finish or cancel them, then stop everything:

   ```bash
   ./stop_services.sh
   ```

   Then take the backup in §5.3.

2. **Fetch the code:**

   ```bash
   git fetch origin && git checkout main && git pull --ff-only origin main && git log -1 --oneline
   ```

3. **Python 3.12 and the backend dependencies** (R16, R17):

   ```bash
   ./setup_production_vm.sh
   ```

   It is idempotent (Python 3.12, Poetry, Node 20, Docker). Then, if the venv was built on
   3.11, rebuild it:

   ```bash
   cd backend && rm -rf .venv && python3.12 -m venv .venv && poetry install --no-interaction
   ```

   Add the system libraries the rehearsal found (typically Pango/Cairo for WeasyPrint) and
   the Playwright browser:

   ```bash
   cd backend && .venv/bin/python -m playwright install --with-deps chromium
   ```

4. **Frontend dependencies** (R23):

   ```bash
   cd frontend && npm ci
   ```

5. **Sandbox images** (R19) — the app user must be in the `docker` group:

   ```bash
   cd backend && bash docker/sandbox/build.sh && bash docker/egress-proxy/build.sh
   ```

6. **Configuration, migrations and key rotation — in this order** (R9–R11):
   1. Edit `backend/.env` from [Appendix A](#appendix-a--configuration-changes): the new
      `ENCRYPTION_MASTER_KEY`, `OLD_ENCRYPTION_MASTER_KEY` set to the old value (§5.1 step
      3), `STREAMING_HOST=gateway.hirebuddha.com`, `STREAMING_PROTOCOL=wss`,
      `FRONTEND_URL`, `INTERNAL_TOKEN`, `EMAIL_LINKS_IN_LOG=false`, limits.
   2. Start only the database and Redis:

      ```bash
      cd backend && docker compose up -d db redis
      ```

   3. Migrate:

      ```bash
      cd backend && .venv/bin/alembic upgrade head && .venv/bin/alembic current
      ```

   4. Re-encrypt — dry run, read the counts, then apply:

      ```bash
      cd backend && .venv/bin/python -m scripts.rotate_encryption_key
      ```

      ```bash
      cd backend && .venv/bin/python -m scripts.rotate_encryption_key --apply
      ```

      An "Aborted, nothing written" means a value decrypts under neither key — stop and
      investigate; do not continue to start-up.
   5. Remove `OLD_ENCRYPTION_MASTER_KEY` from `backend/.env`.
   6. Seed what the new code expects, both idempotent: the registry seed (adds missing SKUs,
      task defaults and the `sandbox-runtime` SKU) only if the rehearsal showed models
      missing in health:

      ```bash
      cd backend && VERTEX_PROJECT_ID=<PROJECT> .venv/bin/python db-scripts/seed_integration_registry.py
      ```

7. **Apache** (R20): back up `/etc/apache2/sites-available`, compare each installed vhost
   with the repo's, then copy the changed ones and drop the retired `streaming.` site.
   `setup_apache.sh` copies only the HTTP vhosts (certbot writes the SSL ones), so it would
   **not** install the updated `-le-ssl.conf` files — copy them by hand, keeping the
   certificate paths certbot wrote:

   ```bash
   sudo cp -a /etc/apache2/sites-available ~/apache-sites-available.pre-merge
   ```

   ```bash
   for f in api gateway app; do for s in .conf -le-ssl.conf; do diff -u /etc/apache2/sites-available/$f.hirebuddha.com$s deploy/apache/$f.hirebuddha.com$s; done; done
   ```

   ```bash
   sudo a2dissite streaming.hirebuddha.com streaming.hirebuddha.com-le-ssl
   ```

   After copying the reviewed files into `/etc/apache2/sites-available/`:

   ```bash
   sudo apache2ctl configtest && sudo systemctl reload apache2
   ```

   Make sure no SSE path (`/api/v1/ai/executions/*/stream`) gets `mod_deflate`.

8. **Start:**

   ```bash
   ./start_services.sh
   ```

   Then confirm nothing listens on 8001 or 8002 and both workers run:

   ```bash
   curl -s localhost:8000/api/v1/health | jq
   ```

   Required: `status: ok`, `unmounted_routers: []`, `worker.status: ok` with one worker on
   `arq:queue` and one on `children`, `models.status: ok`.

### 5.5 Verification in the window (before reopening traffic)

| Check | How | Pass |
|---|---|---|
| Health | `GET /api/v1/health` | as above |
| Sign-in | An existing admin signs in at `https://app.hirebuddha.com` | Signed in (everyone else re-signs in — R25) |
| Account email | Register a test address; receive the verification email; reset its password | Both emails arrive; links point at `FRONTEND_URL` (R15) |
| Credentials decrypt | Integrations page lists providers; one agent run | Run `COMPLETED` with an answer (R10) |
| Child runs | Run a PROCESS with children | Children complete on the `children` queue (R18) |
| Sandbox | Run an agent using `sandbox_code` | Tool succeeds in a container (R19) |
| HITL | Run an entity with a checkpoint; approve | Run parks `PAUSED`, resumes, completes (R31) |
| Run stream | Watch a run page; reload mid-run | Events resume without a gap |
| Telephony | Place one inbound and one outbound test call | Call connects; a `voice_call` run appears with usage rows (R20, R29) |
| Webhook | Register an endpoint, send a signed test delivery | `202`, one job; unsigned → `401` (R26) |
| Billing | Read the test company's wallet and `usage_logs` after the runs | Holds released, costs recorded (R30) |
| Logs | `tail -n 200 logs/backend_api.log logs/arq_worker.log logs/arq_child_worker.log` | No tracebacks, no `gate.failed` |

Reopen traffic only when every row passes. If one fails and cannot be fixed inside the
window, roll back (§6).

### 5.6 External reconfiguration (in the window, then follow up)

- **Webhooks (R26):** for each sender from §5.1, create an endpoint
  (`POST /api/v1/webhook-endpoints`), give the provider the new URL
  `https://gateway.hirebuddha.com/webhook/inbound/{endpoint_id}` and the secret.
- **Telephony (R20):** Twilio and Tata voice URLs, status callbacks and media-stream hosts
  point at `gateway.hirebuddha.com` (port 443, path on the API). Nothing at
  `streaming.hirebuddha.com` or `:8001`.
- **Mobile app (R27):** confirm the version in use performs the stream-token handshake; if
  not, ship it before or with this deploy.
- **API consumers (R28):** paged lists, removed routes, the `/api/v1/social-connections`
  move (the old path works for one release only).
- **Smartflo (VT-15):** one live call to confirm the `success` key; then set
  `TATA_STREAM_SUCCESS_KEY` accordingly.

### 5.7 After go-live

| When | Watch |
|---|---|
| First hour | `/api/v1/health` every few minutes; API and worker logs; `gate.failed` and `agent.memory.retrieval_failed` events; 401/429 rates in the Apache logs (R14, R26) |
| First 00:00 and 01:30 UTC | The daily-credit and Razorpay reconciliation crons (R33) — check their log lines and a sample of wallets |
| First day | Inbound-call refusals (`voice.call.refused`) by company (R29); billing totals vs the previous day (R30); child-run and HITL completion |
| First week | Remove the `/api/social-connections` alias after consumers move; restart the API once to confirm a clean restart; take the first post-merge backup and restore it |

Tag the deployed commit (`defect-fixes-1`) once the first day is clean.

---

## 6. Rollback

**Decide before the window who calls it and by when.** Trigger: any §5.5 check failing
that cannot be fixed in the window, or a production incident in the first hours traced to
the change.

| Situation | Rollback |
|---|---|
| Failure **before** `alembic upgrade` ran | `git checkout pre-defect-fixes`, restore the old `.env`, rebuild the venv if Python changed, `./start_services.sh` |
| Failure **after** migrations, inside the window (no new production writes) | Stop everything; restore the database from the pre-merge dump (or the disk from the `hb-pre-merge-*` snapshot); `git checkout pre-defect-fixes`; restore the old `.env`, old Apache vhosts and the old venv; start. Do **not** use `alembic downgrade` — several migrations drop tables or rewrite data |
| Failure **after reopening traffic** | As above, and accept the loss of every write since go-live, or reconcile them by hand from the new database before restoring. This is why §5.5 must pass before traffic returns |

Keep the pre-merge dump, the disk snapshot and the old `.env` for at least 30 days.

---

## Appendix A — configuration changes

`backend/.env` on the VM. "New" means added on this branch; defaults are the code's.

| Variable | Status | Production value |
|---|---|---|
| `ENCRYPTION_MASTER_KEY` | Now **required**, ≥ 32 chars, HKDF-derived (AU-24) | New random value from the secret store |
| `OLD_ENCRYPTION_MASTER_KEY` | New, temporary — only while running the rotation script | The previous key; remove afterwards |
| `SECRET_KEY` | Unchanged (required) | Keep |
| `STREAMING_HOST` / `STREAMING_PROTOCOL` | Default now `localhost:8000` / `ws` | `gateway.hirebuddha.com` / `wss` |
| `FRONTEND_URL` | New (AU-06/AU-08) — where email links point | `https://app.hirebuddha.com` |
| `EMAIL_LINKS_IN_LOG` | New, default `false` | `false` — never `true` in production |
| `INTERNAL_TOKEN` | Empty or placeholder disables `/internal/event` | A random token, if anything posts internal events |
| `RATE_LIMIT` | `200/minute` per IP on REST | Check against peak traffic |
| `WEBHOOK_RATE_LIMIT` | New, `300/minute` per endpoint | Check against peak deliveries |
| `WS_HANDSHAKE_RATE_LIMIT` | New, `30/minute` per IP | Raise if a NAT'd call centre shares an IP |
| `LIVE_SESSIONS_PER_COMPANY` | New, `20` | Per largest tenant's concurrent calls |
| `RUNS_STARTED_PER_MINUTE` | New, `60` per company (0 = off) | Per largest tenant's bursts |
| `CHILD_WORKER_MAX_JOBS` | `10` concurrent child runs | Per VM size |
| `SANDBOX_CONTAINER_RUNTIME_ENABLED` | Default `true` (TL-01) | `true`; requires the two images |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | **No default any more** (IN-23) | Set if a collector runs, e.g. `http://localhost:4317` |
| `WORKER_METRICS_PORT` / `CHILD_WORKER_METRICS_PORT` / `WORKER_METRICS_ADDR` | New (IN-20): 9101 / 9102 / `127.0.0.1` | Keep loopback until a firewall exists (IN-08) |
| `TATA_STREAM_SUCCESS_KEY` | `sucess` (VT-15) | Confirm with one live Smartflo call |
| `GATEWAY_PORT`, `BACKEND_URL`, `EVENT_BUS_TYPE`, `EVENT_BUS_MAXSIZE` | Removed | Delete from `.env` |

## Appendix B — what was never verified live

From the registers and the progress log ([`REMAINING-DEFECTS-PLAN.md`](REMAINING-DEFECTS-PLAN.md#progress-log)):

| Area | Not verified |
|---|---|
| Payments | Razorpay order, subscription, plan and invoice API calls (only signed test payloads) |
| Sign-in | Real Google and Microsoft OAuth |
| Voice | Azure Realtime against a deployment; Gemini Live billing from a recorded session; WhatsApp replies; the Tata WhatsApp send path (no credentials); Smartflo's success key (VT-15) |
| Video | `/stream/video` end to end — `aiortc` was not installed locally (GW-10) |
| Webhooks | Real signed deliveries from GitHub, Meta, Twilio, LinkedIn, TikTok, X, YouTube |
| LLM | Live runs since the consolidated plan's P7 (Vertex credentials were often expired) |
| Platform | Anything on Linux: the deploy scripts, the sandbox containers on the VM, Apache with the new vhosts and SSE behind it |
| Process | No CI run of any suite |
