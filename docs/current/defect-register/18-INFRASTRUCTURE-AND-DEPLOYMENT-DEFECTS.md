# 18. Infrastructure, Deployment & Operations — Defect Register

> **What this document is:** defects in how the platform is built, deployed, backed up and
> operated — the boot scripts, Apache, Docker, backups, CI and the runbooks — plus the
> improvements that would make it survivable at 3am.
> **Source document:** [`18-infrastructure-and-deployment.md`](../18-infrastructure-and-deployment.md)
> **Compiled:** 2026-09-01, against branch `fresh-main`.
> **Context:** everything runs on **one VM** with **monthly backups stored on the same
> disk**. Those two facts together are the most serious thing in this register.

---

## How to read this file

- **✅ Verified** — the file or config was read on 2026-09-01 and the claim held.
- **📄 Doc-reported** — from `18-infrastructure-and-deployment.md`, not independently
  re-checked.
- Severity here means **what happens when something goes wrong**, not how likely it is.
  A monthly backup is fine until the day it is not.

---

## Contents

1. [Summary](#1-summary)
2. [T0 — Data loss and recovery](#2-t0--data-loss-and-recovery)
3. [T1 — Not production-ready as configured](#3-t1--not-production-ready-as-configured)
4. [T2 — Traps in the scripts and configs](#4-t2--traps-in-the-scripts-and-configs)
5. [T3 — Operability](#5-t3--operability)
6. [Improvements](#6-improvements)
7. [Suggested order of work](#7-suggested-order-of-work)

---

## 1. Summary

| Tier | Theme | Count | When to do it |
|---|---|---|---|
| [T0](#2-t0--data-loss-and-recovery) | Data loss and recovery | 4 | **Now** |
| [T1](#3-t1--not-production-ready-as-configured) | Not production-ready as configured | 6 | Before the next deployment |
| [T2](#4-t2--traps-in-the-scripts-and-configs) | Traps in the scripts and configs | 6 | Now — all cheap |
| [T3](#5-t3--operability) | Operability | 5 | Before the first on-call rotation |

**Total: 21 defects, 10 improvements.**

The three to read first:

- **[IN-01](#in-01--backups-are-monthly-and-on-the-same-disk-as-the-database)** — up to 31
  days of data loss, and a disk failure loses the backups too.
- **[IN-02](#in-02--the-backup-script-writes-to-a-path-that-does-not-exist-here)** — the
  defaults point at an older checkout, so backups may not be running at all.
- **[IN-05](#in-05--the-repository-has-no-functioning-ci)** — the one workflow filters on a
  directory that no longer exists. It has never fired.

---

## 2. T0 — Data loss and recovery

### IN-01 — Backups are monthly and on the same disk as the database

**✅ Verified · Critical**

`setup_cron.sh` registers `db_backup.sh` at `0 2 1 * *` — 02:00 on the **1st of each
month**. Retention is 90 days.

So the recovery point objective is up to **31 days**. For a platform holding conversation
transcripts, billing ledgers and encrypted third-party credentials, that means a failure on
the 30th loses a month of everything.

`BACKUP_ROOT` also defaults to a path **inside the repository**, so the dumps live on the
same disk as the database they protect. One disk failure loses both.

- [`deploy/backup/setup_cron.sh`](../../../deploy/backup/setup_cron.sh)
- [`deploy/backup/db_backup.sh:28`](../../../deploy/backup/db_backup.sh:28)

**Fix, in order:** daily dumps first, off-host storage second, WAL archiving third.

---

### IN-02 — The backup script writes to a path that does not exist here

**✅ Verified · Critical**

```bash
BACKUP_ROOT="${BACKUP_ROOT:-/home/rahul/workspace/hb-proto-3/deploy/backup/dumps}"
LOG_DIR="${LOG_DIR:-/home/rahul/workspace/hb-proto-3/deploy/backup/logs}"
```

`hb-proto-3` is an **older checkout**. This repository is at
`/home/rahul/workspace/hire-buddha-app`. The cron line in the script header points at the
same stale path.

`mkdir -p` will happily create the old directory, so the script does not error — it writes
backups somewhere nobody is looking, or writes them into a directory that a later cleanup
removes.

Combined with [IN-01](#in-01--backups-are-monthly-and-on-the-same-disk-as-the-database),
the honest statement is: **nobody has verified that a usable backup exists.**

- [`deploy/backup/db_backup.sh:12`](../../../deploy/backup/db_backup.sh:12), [`:28`](../../../deploy/backup/db_backup.sh:28), [`:29`](../../../deploy/backup/db_backup.sh:29)

**Fix:** derive the paths from the script's own location, and check the newest dump before
trusting anything else in this section.

---

### IN-03 — There is no restore test

**📄 Doc-reported · High**

The document gives a restore command. Nothing runs it. A `pg_dump` that has never been
restored is a file, not a backup — and this one uses `--no-owner --no-privileges`, so the
restore will not recreate roles or grants.

**Fix:** a monthly job that restores the newest dump into a scratch database and runs one
sanity query. Anything less is unverified.

---

### IN-04 — `docker compose down -v` deletes the database

**📄 Doc-reported · High**

Both Postgres and Redis use named volumes. `stop_services.sh` correctly runs
`docker compose down` **without** `-v`, so data survives a normal stop/start.

Recorded because the destructive variant is one character away, it appears in Docker
documentation everywhere, and with
[IN-01](#in-01--backups-are-monthly-and-on-the-same-disk-as-the-database) the recovery is up
to a month old.

---

## 3. T1 — Not production-ready as configured

### IN-05 — The repository has no functioning CI

**✅ Verified · Critical**

There is exactly one GitHub Actions workflow, and it triggers on:

```yaml
paths: ["backend/cortex_memory/**"]
```

That directory is now `backend/cortex_memory_moved_to_pypi_repo/`. The filter matches
nothing, so **the workflow has never fired** — and its `working-directory: backend` plus
`pip install -e cortex_memory[dev]` would fail if it did.

Nothing in CI runs `backend/tests/` (1,063 tests), the layout lint, ruff, black, or the
frontend build. `scripts/run_ci_matrix.sh` defines three lanes wired to no trigger.

The workflow appears green in the repository listing because it has no runs.

- [`.github/workflows/cortex-memory.yml:11`](../../../.github/workflows/cortex-memory.yml:11)
- Also recorded as **D-14** in the platform register

**Fix first.** Every guardrail in every other register in this set is blocked on this.

---

### IN-06 — The Dockerfile runs as root with `--reload`

**✅ Verified · High**

```dockerfile
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

No `USER` directive, so the process runs as **root**, and `--reload` starts a file-watching
reloader — extra processes, extra memory, and a code-reload path that should not exist in
production.

That matters more than usual here: `SubprocessRuntime` executes LLM-authored code **as the
API process's own OS user**
([TL-01](TOOL-LAYER-DEFECTS.md#tl-01--the-default-sandbox-runs-llm-authored-code-as-the-backend-os-user)).
In this container, that user is root.

The container path is not the deployed one today — `start_services.sh` runs the processes
on the host — but it is the one anyone containerising will reach for.

- [`backend/Dockerfile`](../../../backend/Dockerfile)

---

### IN-07 — The security config blocks a live static mount

**✅ Verified · High**

`hirebuddha-security.conf` denies:

```apache
<LocationMatch "^/(uploads|shell|cmd|c99|r57|webshell)(/|$)">
```

`main.py` mounts `/uploads` as a real `StaticFiles` directory holding profile pictures.

So every profile picture 403s in production, and the failure looks like a broken image
rather than a deliberate block.

- [`deploy/apache/hirebuddha-security.conf:168`](../../../deploy/apache/hirebuddha-security.conf:168)
- [`backend/src/main.py:72`](../../../backend/src/main.py:72)

**Fix:** remove `uploads` from the pattern, or move the mount to `/artifact/user-uploads`,
which is where new files already go.

---

### IN-08 — No firewall configuration exists in the repository

**📄 Doc-reported · High**

Nothing restricts direct access to ports 3000, 8000, 8001, 5433 or 6379 if the VM is
internet-facing. Redis in particular has no password
([SA-05](02-SYSTEM-ARCHITECTURE-DEFECTS.md#sa-05--the-workers-redis-parser-throws-away-password-tls-and-database-index)
notes the URL parser would discard one anyway).

The entire security model assumes Apache is the only reachable surface, and nothing in the
repository enforces that. It may be handled by cloud security groups — but that is an
assumption, not a configuration.

---

### IN-09 — No log rotation

**📄 Doc-reported · High**

`start_services.sh` writes four log files into `logs/` with `nohup` and never rotates them.
The document names this as the most likely cause of a full disk.

`ExecutionDetail`'s never-stopping poll
([FE-19](16-FRONTEND-DEFECTS.md#fe-19--the-execution-poll-never-stops)) makes it worse: one
open browser tab produces roughly 1.3 access-log lines per second, forever.

**Fix:** a `logrotate` config. Ten lines.

---

### IN-10 — Three different Python versions

**✅ Verified · Medium**

| Where | Version |
|---|---|
| `setup_production_vm.sh` | 3.12 |
| `pyproject.toml` | `^3.11` |
| `backend/Dockerfile` | `python:3.11-slim` |

What is developed against, what is declared, and what a container runs are three different
things.

---

## 4. T2 — Traps in the scripts and configs

| ID | Trap | Notes | Status |
|---|---|---|---|
| **IN-11** | `stop_services.sh` runs a blanket `pkill -f "uvicorn"` | Line 78. It kills **any** uvicorn process on the machine, not just this platform's. Dangerous on a shared or multi-app host | ✅ Verified |
| **IN-12** | `.env.example` ships with port 5432 | Postgres is on host port **5433**. Nothing connects until it is fixed, and the error is a generic connection refusal. Also **D-45** | 📄 Doc-reported |
| **IN-13** | `backend/.env` exists in the working tree | It is `.gitignore`d (confirmed) and currently matches `.env.example` byte-for-byte. Safe today; the risk is someone adding real secrets to a file that already exists locally and assuming it is tracked | ✅ Verified |
| **IN-14** | `npm install` requires `--legacy-peer-deps` | Without it, installation fails on React Three Fiber peer conflicts — for a dependency that powers a decorative background ([FE-17](16-FRONTEND-DEFECTS.md#fe-17--the-webgl-background-never-sleeps)) | 📄 Doc-reported |
| **IN-15** | `streaming.hirebuddha.com` reuses the gateway certificate | So does `api.hirebuddha.com`. Renewing one certificate affects three hostnames, and a missing SAN entry produces a hostname mismatch. Also **D-43** context | 📄 Doc-reported |
| **IN-16** | Two competing `*:80` vhosts for `app.hirebuddha.com` | `app.hirebuddha.com.conf` declares one; `app.hirebuddha.com-le-ssl.conf` declares a **second** at line 20 with the HTTPS redirect commented out. Whichever Apache loads first wins | ✅ Verified |

---

## 5. T3 — Operability

### IN-17 — `core/` is 20 lines from its lint cap

**📄 Doc-reported · Medium**

`lint_ai_layout.py` caps `core/` at 1,500 lines and `agent_loop.py` is ~1,480. The next
substantive change to the control loop fails the lint.

The cap is deliberately a ratchet — the file's own comment says never to raise one. So the
next kernel change must also be a refactor, whether or not that is the right time for one.

- [`backend/scripts/lint_ai_layout.py`](../../../backend/scripts/lint_ai_layout.py)

---

### IN-18 — Quality gates exist and run only when someone remembers

**📄 Doc-reported · High**

Three real, working gates with no trigger:

| Gate | What it enforces |
|---|---|
| `lint_ai_layout.py` | 271 lines of architecture policy — package caps, forbidden imports, the `tools/` root rule |
| `typecheck_ai.py` | incremental strict typing |
| `run_ci_matrix.sh` | three lanes: fast, full, typing |

All must be invoked by hand. Blocked on
[IN-05](#in-05--the-repository-has-no-functioning-ci).

---

### IN-19 — The observability stack does not work out of the box

**📄 Doc-reported · Medium**

Two problems in `docker-compose.observability.yml` and its config:

- `prometheus.yml` scrapes `host.docker.internal:8000`, which does not resolve on stock
  Linux Docker without an `extra_hosts` entry.
- The Grafana container publishes **port 3000**, colliding with the Vite dev server.

Both are one-line fixes, and both are discovered during an incident — which is the only
time anyone starts this stack.

---

### IN-20 — The gateway and the worker have no tracing

**✅ Verified · Medium**

`setup_telemetry` is called once, on the last line of `main.py`. The gateway has its own
hand-rolled `/metrics/gateway` JSON endpoint and no OpenTelemetry. The worker has neither.

The worker is where every agent execution runs. So the process doing the expensive work is
the one with no distributed tracing and no metrics endpoint.

- [`common/telemetry.py`](../../../backend/src/common/telemetry.py)

---

### IN-21 — There is no rollback procedure beyond `git checkout`

**📄 Doc-reported · Medium**

The rollback runbook is: check out the previous commit and restart. There are no tagged
releases, no build artefacts, and — because the frontend is served by a dev server
([SA-I1](02-SYSTEM-ARCHITECTURE-DEFECTS.md#sa-i1--serve-the-frontend-as-a-build-not-a-dev-server))
— no way to roll back the frontend independently of the backend.

Database migrations have `downgrade` functions, but nothing in the runbook says when to run
them, and several migrations are defensively idempotent in ways that make a downgrade
uncertain ([DM-20](03-DATA-MODEL-DEFECTS.md#dm-20--some-migrations-are-defensively-idempotent-because-environments-drifted)).

---

## 6. Improvements

### IN-I1 — Fix CI first

**Effect: everything else depends on it.**
[IN-05](#in-05--the-repository-has-no-functioning-ci). Change the `paths` filter, add a
second workflow that runs `backend/tests/`, `lint_ai_layout.py`, ruff and the frontend
build.

Three registers in this set name a "census" guardrail — route, schema, registry, dependency
— and none of them can exist until there is somewhere to run them.

### IN-I2 — Daily off-host backups, and one restore test

**Effect: large.** [IN-01](#in-01--backups-are-monthly-and-on-the-same-disk-as-the-database),
[IN-02](#in-02--the-backup-script-writes-to-a-path-that-does-not-exist-here),
[IN-03](#in-03--there-is-no-restore-test).

In order: fix the paths, move the cron to daily, push the dump to object storage, then add
a monthly restore-and-verify job. The first two are minutes; the RPO goes from 31 days to
one.

### IN-I3 — Add log rotation

**Effect: medium, prevents an outage.**
[IN-09](#in-09--no-log-rotation). A `logrotate` config for `logs/*.log`. The most likely
cause of a full disk, and a full disk stops Postgres.

### IN-I4 — Harden the Dockerfile

**Effect: medium.** [IN-06](#in-06--the-dockerfile-runs-as-root-with---reload). Add a
non-root `USER`, drop `--reload`, and use a multi-stage build so the image does not carry
build tooling. Whoever containerises this next will otherwise inherit a root process
running LLM-authored code.

### IN-I5 — Commit a firewall configuration

**Effect: medium.** [IN-08](#in-08--no-firewall-configuration-exists-in-the-repository).
Even a `ufw` script in `deploy/` that allows 80/443 and denies the rest turns an assumption
into a checked-in artefact. Today nobody can tell from the repository whether the platform's
internal ports are exposed.

### IN-I6 — Instrument the worker and the gateway

**Effect: large for operability.** [IN-20](#in-20--the-gateway-and-the-worker-have-no-tracing).
`setup_telemetry` is 32 lines and already written. Calling it from the gateway, and wiring
`events.set_otel_exporter` in the worker, makes the two processes that do the real work
visible.

Pairs with [SA-I4](02-SYSTEM-ARCHITECTURE-DEFECTS.md#sa-i4--give-the-worker-a-health-signal)
— a worker heartbeat, so a dead worker is an alarm rather than a pile of `PENDING` runs.

### IN-I7 — Build and version the frontend

**Effect: large.** Serving the SPA from `vite` in production means no minification, no
asset hashing, a larger attack surface, and no way to roll the frontend back independently
([IN-21](#in-21--there-is-no-rollback-procedure-beyond-git-checkout)).

`npm run build` plus an Apache `DocumentRoot` removes a whole process from the box. Same
item as [SA-I1](02-SYSTEM-ARCHITECTURE-DEFECTS.md#sa-i1--serve-the-frontend-as-a-build-not-a-dev-server)
and [FE-I10](16-FRONTEND-DEFECTS.md#fe-i10--build-the-frontend-for-production).

### IN-I8 — Make `stop_services.sh` precise

**Effect: small, prevents a bad day.**
[IN-11](#4-t2--traps-in-the-scripts-and-configs). The script already writes PID files and
already kills by port. The blanket `pkill -f "uvicorn"` at the end is a belt-and-braces step
that will one day kill someone else's application.

### IN-I9 — Pin one Python version

**Effect: small.** [IN-10](#in-10--three-different-python-versions). Pick 3.12 (what the VM
installs), update `pyproject.toml` and the Dockerfile, and add it to the CI matrix once
[IN-I1](#in-i1--fix-ci-first) exists.

### IN-I10 — Write the four census checks

**Effect: large, once CI exists.** The platform register names four mechanical checks, each
minutes to write and seconds to run:

| Check | Compares | Catches |
|---|---|---|
| Route census | router decorators vs [17](../17-api-reference.md) | dead routers, undocumented routes, mount-order mistakes |
| Schema census | `__tablename__` and columns vs [03](../03-data-model.md) | missing migrations ([DM-01](03-DATA-MODEL-DEFECTS.md#dm-01--subscription_tiers-has-no-migration), [DM-02](03-DATA-MODEL-DEFECTS.md#dm-02--phone_numbers-is-created-by-a-script-not-a-migration)) |
| Registry census | `ToolRegistry.register` calls vs [09](../09-tools.md) | unregistered and deprecated-but-exposed tools |
| Dependency census | adapter imports vs `pyproject.toml` and the venv | [LP-07](10-LLM-PROVIDERS-DEFECTS.md#lp-07--any-claude-integration-fails-on-its-first-call) (anthropic) and [GW-10](13-GATEWAY-AND-REALTIME-DEFECTS.md#gw-10--aiortc-is-not-installed-and-the-video-path-has-a-second-bug-behind-it) (aiortc) |

Between them they would have caught eight defects across this register set.

---

## 7. Suggested order of work

| Step | Work | Why here |
|---|---|---|
| **1** | IN-02, then IN-I2 | Check whether a usable backup exists at all, then fix the paths and the schedule |
| **2** | IN-I1 / IN-05 | CI. Nothing else can be enforced without it |
| **3** | IN-I3 / IN-09, IN-07 | Log rotation and the `/uploads` block. Both are minutes |
| **4** | IN-I5 / IN-08, IN-I8 / IN-11 | Firewall config; make the stop script precise |
| **5** | IN-I6 / IN-20 | Instrument the worker and the gateway |
| **6** | IN-I10 | The four census checks, now that CI can run them |
| **7** | IN-I7 / IN-21, IN-I4 / IN-06 | Production build and a hardened image |
| **8** | IN-17, IN-I9 / IN-10 | The `core/` refactor and one Python version |

---

## Where to go next

- [18 — Infrastructure, deployment & operations](../18-infrastructure-and-deployment.md) —
  the source document, including the runbooks.
- [`DEFECT-REGISTER.md`](../DEFECT-REGISTER.md) — IN-05 is D-14, IN-12 is D-45, and §9
  Guardrails is IN-I10.
- [02 — System architecture](02-SYSTEM-ARCHITECTURE-DEFECTS.md) — SA-01, SA-02, SA-14 for
  the vhosts and the port-8002 removal.
- [19 — Testing](19-TESTING-DEFECTS.md) — what CI would actually run.
- [16 — Frontend](16-FRONTEND-DEFECTS.md) — FE-I10 for the production build.
