# CI/CD — taking a change from your laptop to production

> **For:** whoever ships HireBuddha changes (today the owner and engineering).
> **Written:** 22 Oct 2026, after the first pipeline release reached production (`7ce09ec`, run 39623875577).
> **Covers:** Azure dev and Azure production, in two ways: **A. automated** (GitHub Actions, the normal way) and **B. manual** (your own machine, when the pipeline cannot be used).
> **Decisions behind it:** D46 (Phase 14 stays off `main` for now), D49–D52 (production the same size as dev, no staging, dev first, a reviewer approves production).

---

## 0. The picture

```
 your laptop                 GitHub                           Azure dev                     Azure production
 ───────────                 ──────                           ─────────                     ────────────────
 code + local checks  ──push──►  ci (tests, charts)
                                    │ pass
                                    ▼
                                 images ──build+push──►  acrhbdevac48  (12 images, tag = commit sha)
                                    │
                                    ▼
                                 dev ─────helm upgrade──►  aks-hb-dev  (migrations Job, pods, smoke test)
                                    │ pass
                                    ▼
                                 prod  ⏸ waits for a reviewer (environment azure-prod)
                                    │ approved
                                    ├──copy same digests──────────────────────────────►  acrhbprode7b3
                                    └──helm upgrade───────────────────────────────────►  aks-hb-prod
```

Production only ever gets the images dev already ran, with the same tag and the same digest. Nothing is built just for production, and there is no staging.

### 0.1 The two environments

| | Dev | Production |
|---|---|---|
| Screens / API | `https://app.azdev.hirebuddha.com` / `https://gateway.azdev.hirebuddha.com` | `https://app.azprod.hirebuddha.com` / `https://gateway.azprod.hirebuddha.com` |
| Health | `https://gateway.azdev.hirebuddha.com/api/v1/health` | `https://gateway.azprod.hirebuddha.com/api/v1/health` |
| Cluster | `aks-hb-dev` in `rg-hb-dev-aks` | `aks-hb-prod` in `rg-hb-prod-aks` |
| Image registry | `acrhbdevac48` | `acrhbprode7b3` |
| Key Vault | `kv-hb-dev-ac48` | `kv-hb-prod-e7b3` |
| Chart values | `infra/k8s/env/dev/hb-platform.yaml` | `infra/k8s/env/prod/hb-platform.yaml` |
| Names and ids | `infra/azure/env/dev.env` | `infra/azure/env/prod.env` |
| GitHub environment | `azure-dev` (no approval) | `azure-prod` (required reviewer: the owner) |
| Hours | **Mon–Sat 09:00–21:00 IST** (Logic Apps start and stop it, to save money) | Always on |
| Tenant runtime (slice 4: sandboxes, apps, Gitea) | On | Off for now |

### 0.2 What the pipeline deploys, and what it does not

The pipeline (and way B's §3) rolls out **one thing**: the `hb-platform` Helm release, meaning the images, the chart and the env values file. That release includes the **database migrations**, which a Helm pre-upgrade Job runs before the new pods start.

These are **never deployed by the pipeline**. You change them by hand in both ways (§4):

| Change | How |
|---|---|
| Azure resources (`infra/azure/bicep/**`, `*.bicepparam`): pools, databases, Key Vault, identities, budgets | `az deployment sub what-if` then `create` (§4.1) |
| Cluster bootstrap (`infra/k8s/charts/hb-bootstrap/**`, `infra/k8s/env/*/hb-bootstrap.yaml`): namespaces, service accounts, cluster RBAC, Gateway, cert-manager | `bash infra/k8s/bootstrap/install.sh <env>` (§4.2) |
| A new Key Vault secret (a new `secrets.csi.objects` entry in the values) | `az keyvault secret set` **before** the release that reads it (§4.3) |
| Database roles and grants (`infra/azure/sql/**`) | `psql` as a database admin (§4.4) |
| GitHub variables, environments and reviewers | GitHub settings, or `gh variable set` (§2.1) |
| The CORTEX memory package | Its own repository and workflow (`cortex-memory.yml` only tests the local copy) |

---

## 1. On your laptop (both ways start here)

### 1.1 Branch

* While Phase 14 stays off `main` (D46), work on **`roadmap-development-defect-fixes`**. A push to that branch, or to `main`, starts the pipeline.
* A short-lived feature branch is fine. Open a pull request into `roadmap-development-defect-fixes`: `ci.yml` runs on every pull request, but nothing deploys until the change is merged and pushed to the deploy branch.

### 1.2 Run it locally

From the repository root on Windows (PowerShell):

```powershell
.\start_services.ps1
```

This starts PostgreSQL (5433) and Redis with docker compose, then the API on :8000, the three Arq workers, the scheduler and the Vite frontend on :3000. Workers don't reload on code changes, so after a backend change run `.\stop_services.ps1 -Only workers; .\start_services.ps1 -Only workers`. If the Docker engine came up empty, rebuild the local databases first (`backend/`): `docker compose --profile azure up -d db redis azurite`, then `python -m src.common.tenancy.migrate control`, then the seeds in `db-scripts/`.

### 1.3 The checks the pipeline will run — run them first

The pipeline runs exactly these (`.github/workflows/ci.yml`). A failure there stops the deploy, so it's quicker to catch it here.

**Backend** (in `backend/`, with the project's virtualenv; set `PYTHONUTF8=1` on Windows):

```bash
cd backend
.venv/Scripts/python -m src.common.tenancy.migrate control                  # migrations up
.venv/Scripts/alembic -n tenant_platform -x schema=public downgrade -1      # one down, tenant tree
.venv/Scripts/alembic downgrade -1                                         # one down, control tree
.venv/Scripts/python -m src.common.tenancy.migrate control                  # and up again
.venv/Scripts/python scripts/lint_ai_layout.py
.venv/Scripts/python scripts/typecheck_ai.py
.venv/Scripts/python -m pytest tests/unit tests/ai -q -m "not (integration or e2e or parity or regression or chaos or docker)"
.venv/Scripts/python -m pytest tests/integration -q -m "not (slow or docker)"
```

Run the migration round-trip against a scratch database, not the one you work in.

**Frontend** (in `frontend/`):

```bash
cd frontend
npm run lint                     # zero warnings allowed
npx tsc --noEmit -p tsconfig.json
npm test
npx vite build
```

**Charts** (only when you touched `infra/k8s/**`). Helm runs from its Docker image if it isn't installed:

```bash
C=infra/k8s/charts/hb-platform
helm lint $C -f $C/values-azure.yaml -f infra/k8s/env/dev/hb-platform.yaml
helm template hb-platform $C -n hb-platform -f $C/values-azure.yaml -f infra/k8s/env/dev/hb-platform.yaml  > /tmp/dev.yaml
helm template hb-platform $C -n hb-platform -f $C/values-azure.yaml -f infra/k8s/env/prod/hb-platform.yaml > /tmp/prod.yaml
```

Read the diff of the rendered production manifests whenever you change a template. A change meant for dev often turns something on in production too.

### 1.4 Rules a change must follow to be deployable

1. **Migrations are backward compatible.** The migrations Job runs *before* the new pods, while the old pods are still serving. A rollback (§5) does not undo a migration. So add columns and tables first and use them in a later release, and only remove a column after no released code reads it.
2. **Migrations cover every tenant.** `python -m src.common.tenancy.migrate all` migrates the control database, then every tenant database (split mode). A migration that fails for one tenant fails the release.
3. **Settings come from the values or Key Vault, never from code.** A new secret is created in both Key Vaults before the release that reads it (§4.3).
4. **No secret in the repository**, the values files or a commit message.
5. **Commit everything.** An image's tag is the commit sha, so the tag only means something if the commit holds all the code that went into the image.

### 1.5 Commit

```bash
git add <files>
git commit -m "fix(area): what changed and why"
```

---

## 2. Way A — automated (GitHub Actions)

### 2.1 One-time setup (done 21 Oct 2026; check it if something changed)

| Where | What |
|---|---|
| Repository variables | `AZURE_DEPLOY_ENABLED=true` (dev jobs on), `AZURE_PROD_ENABLED=true` (prod job on). If either is false, its jobs are **skipped**, not failed. |
| Environment `azure-dev` | `AZURE_CLIENT_ID` (id-hb-dev-ci), `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `ACR_NAME=acrhbdevac48`, `AKS_NAME=aks-hb-dev`, `AKS_RESOURCE_GROUP=rg-hb-dev-aks` |
| Environment `azure-prod` | the same for production (`acrhbprode7b3`, `aks-hb-prod`, `rg-hb-prod-aks`), plus `SOURCE_ACR_NAME=acrhbdevac48`, and **Required reviewers: the owner** |
| Azure | Each CI identity (`id-hb-<env>-ci`) trusts GitHub's OIDC token for `repo:gondolerahul@158562688/hire-buddha-app@1332013197:environment:azure-<env>`. It holds AcrPush on its registry, AKS RBAC Admin on the `hb-platform` and `hb-system` namespaces, and (production only) AcrPull on dev's registry. No Azure secret is stored in GitHub. |

Check them with:

```bash
gh variable list
gh variable list --env azure-dev
gh variable list --env azure-prod
```

### 2.2 Push

```bash
git push origin roadmap-development-defect-fixes
```

The `deploy-azure` workflow starts when the push touches `backend/**`, `frontend/**`, `infra/k8s/**` or the workflow file itself. A push that only changes docs or `infra/azure/**` doesn't deploy. Run it by hand from **Actions → deploy-azure → Run workflow** if you need to.

Watch it in **GitHub → Actions → deploy-azure → the run**, or from a terminal:

```bash
gh run list --workflow deploy-azure --limit 3
gh run watch <run-id>
```

### 2.3 What the run does, job by job

| # | Job | What happens | Typical time |
|---|---|---|---|
| 1 | `ci / backend`, `ci / frontend`, `ci / charts` | The checks of §1.3. The backend runs on PostgreSQL 16, Redis and Azurite with `PLATFORM_PROFILE=local`, so a hidden Azure dependency fails it. The charts job lints, renders default/dev/prod/on-premise, validates them with kubeconform, and checks that the on-premise render has nothing Azure-only. | 10–20 min |
| 2 | `images` (11 in parallel) | Signs in to Azure as `id-hb-dev-ci` (OIDC). Builds `hb-api`, `hb-worker`, `hb-child-worker`, `hb-event-worker`, `hb-scheduler`, `hb-backup`, `hb-frontend`, `hb-sandbox`, `hb-checks`, `hb-egress-proxy` and `hb-caddy-redis`, with provenance and an SBOM, and pushes each to `acrhbdevac48/<image>:<sha>`. | 5–15 min |
| 3 | `app-controller` | Builds `hb-app-controller` on top of that release's `hb-api` image and pushes it. | 2–4 min |
| 4 | `dev` | `helm upgrade --install hb-platform … -f values-azure.yaml -f env/dev/hb-platform.yaml --set global.imageTag=<sha> --atomic --wait --timeout 20m`. Helm first runs the hooks (Key Vault secret classes, Google federation config, **the migrations Job**), then rolls the pods. Then the smoke test: `rollout status deploy/hb-api` and `curl http://hb-api:8000/api/v1/health` from a throwaway pod. | 3–10 min |
| 5 | `prod` | **Waits for approval** (§2.5). Then, as `id-hb-prod-ci`: copies all 12 images from dev's registry to production's with `docker buildx imagetools create`, which keeps the same digests, and runs the same rollout and smoke test with `env/prod/hb-platform.yaml`. | 5–10 min after approval |

`--atomic` means a failed or timed-out rollout is **rolled back automatically** to the previous release. The old pods keep serving, and the job fails.

### 2.4 Check dev before approving production

Approving is your decision, so look at dev first:

1. Open `https://gateway.azdev.hirebuddha.com/api/v1/health`. You want `"status":"ok"`, a worker on all four queues, and models `ok`.
2. Open `https://app.azdev.hirebuddha.com`, sign in, and try what the change touched.
3. Optional: from a terminal with cluster access (§3.1), `kubectl --context aks-hb-dev -n hb-platform get pods`. Every pod should be `Running` with no restarts on the new image tag.
4. For a bigger change, run the relevant parts of [PRODUCTION_MANUAL_TEST_PLAN.md](PRODUCTION_MANUAL_TEST_PLAN.md) on dev. The isolation suite (`backend/tests/isolation`) runs **on dev only**, never on production.

### 2.5 Approve (or reject) production

1. GitHub → **Actions** → the run → the yellow banner **"Review pending deployments"**.
2. Tick **azure-prod**, add a comment if you like (e.g. what you checked), then **Approve and deploy**. Or **Reject**, which ends the run with dev deployed and production untouched.
3. The approval request expires after 30 days. A rejected or expired run can't be resumed, so push again or use **Re-run jobs**.

From the terminal: `gh run view <run-id>` shows the job waiting. Approval itself is done on the website.

### 2.6 Check production

1. `https://gateway.azprod.hirebuddha.com/api/v1/health`: `ok`, as in §2.4.
2. `https://app.azprod.hirebuddha.com`: sign in, then a light smoke check (§1 of the manual test plan, 10 minutes).
3. Optional: `helm --kube-context aks-hb-prod -n hb-platform history hb-platform --max 3` shows the new revision as `deployed`. `kubectl --context aks-hb-prod -n hb-platform get pods` shows every pod on the new tag from `acrhbprode7b3`.

### 2.7 Things to know about the automated way

* **Dev's hours.** Dev stops at 21:00 IST and on Sundays. A push outside those hours fails the `dev` job, because the cluster can't be reached, and production never gets the change. Either push in working hours, or start dev first (§3.1 has the commands; about ₹60 an hour outside the schedule) and rerun the failed jobs.
* **One deploy at a time per branch.** Runs share the concurrency group `deploy-<branch>` and don't cancel a running deploy. A run **waiting for production approval counts as running**. A newer push waits behind it, and if a third push comes, GitHub replaces the waiting one with it. So before pushing again, either approve or reject the pending run. Otherwise your new commit sits in the queue until you do.
* **Rejecting is safe.** Dev keeps the new version and production keeps the old one. The next push brings both forward again.
* **Every push goes to dev.** There is no "deploy to dev only" switch: rejecting the production step is how you keep a change on dev.
* **Re-running.** **Re-run failed jobs** reuses the images the run already built, as long as the `images` job succeeded.

### 2.8 When a job fails

| Failing step | Usual cause | What to do |
|---|---|---|
| `ci / backend` | A test, the migration round-trip, or the layout/type gate | Reproduce with §1.3, fix, commit, push |
| `ci / frontend` | Lint warning, type error, test, build | `npm run lint` / `npx tsc` / `npm test` locally |
| `ci / charts` | Template error, schema error, Azure-only content in the on-premise render | `helm lint` / `helm template` locally (§1.3) |
| `images` → `azure/login` | OIDC subject not trusted (`AADSTS700213`), or a wrong `AZURE_CLIENT_ID` | Check the identity's federated credential subject (§2.1) |
| `images` → build | Dockerfile or dependency error | `docker build --target <t> backend` locally |
| `dev` → credentials | Dev cluster stopped (outside hours) | Start dev (§3.1), then **Re-run failed jobs** |
| `dev` → helm, `forbidden` | The chart now creates something the CI identity may not (cluster-scoped objects, another namespace) | Move it to `hb-bootstrap` (§4.2), or grant the identity rights there via Bicep |
| `dev` → helm, timeout, rolled back | A pod doesn't become ready: image, settings, secrets or the migration | See "Reading a failed rollout" below |
| `dev` → helm, migrations Job failed | A migration error, or one tenant database failing | Read its log (below); fix forward, since the old release keeps running |
| `prod` → copy images | Production's identity lost AcrPull on dev's registry | Bicep `promotionSourceRegistry` (§4.1) |
| `prod` → helm | As for dev, but on production | As for dev; production keeps its previous release |

**Reading a failed rollout** (needs cluster access, §3.1):

```bash
kubectl --context aks-hb-dev -n hb-platform get pods
kubectl --context aks-hb-dev -n hb-platform describe pod <pod>         # events: image pull, secrets mount, scheduling
kubectl --context aks-hb-dev -n hb-platform logs <pod> --previous      # why the container exited
kubectl --context aks-hb-dev -n hb-platform get jobs                   # a failed hb-migrations-<revision> stays
kubectl --context aks-hb-dev -n hb-platform logs job/hb-migrations-<revision>
helm --kube-context aks-hb-dev -n hb-platform history hb-platform --max 5
```

A successful migrations Job deletes itself. A failed one stays, so you can read its log.

---

## 3. Way B — manual (from your machine)

Use it when the pipeline can't be used: GitHub Actions is down, a hotfix is needed while the pipeline itself is broken, or you're testing a chart change on dev before committing it. **Production still only gets images that ran on dev.** Never build an image for production directly.

Run the commands in Git Bash from the repository root. Under Git Bash, prefix a command with `MSYS_NO_PATHCONV=1` when an argument starts with `/` (for example, paths inside a pod).

### 3.1 Tools and access

* **Tools:** Azure CLI, `kubelogin`, `kubectl`, Helm **3.16.3** (the pipeline's version), Docker. On an ARM machine (Apple silicon), add `--platform linux/amd64` to every `docker build`.
* **Rights:** membership in the environment's admins Entra group (`ADMINS_GROUP_ID` in `infra/azure/env/<env>.env`). It is the cluster's admin group and holds Key Vault Administrator. Pushing and importing images also needs AcrPush on the registries; the subscription's Owner (today, the owner's account) has every right needed here.
* **Sign in and get both clusters:**

```bash
az login
az account set --subscription af133a07-d04f-4d5d-928b-d532a3abf0f4
az aks get-credentials -g rg-hb-dev-aks  -n aks-hb-dev  --context aks-hb-dev  --overwrite-existing
az aks get-credentials -g rg-hb-prod-aks -n aks-hb-prod --context aks-hb-prod --overwrite-existing
kubelogin convert-kubeconfig -l azurecli
kubectl --context aks-hb-dev get nodes
```

* **Dev outside its hours:**

```bash
# Start: the databases first, then the cluster (about 10 minutes)
az postgres flexible-server start -g rg-hb-dev-data -n psql-hb-dev-control
az postgres flexible-server start -g rg-hb-dev-data -n psql-hb-dev-pool-01
az aks start -g rg-hb-dev-aks -n aks-hb-dev
# Stop it again when you are done: the cluster first, then the databases
az aks stop -g rg-hb-dev-aks -n aks-hb-dev
az postgres flexible-server stop -g rg-hb-dev-data -n psql-hb-dev-control
az postgres flexible-server stop -g rg-hb-dev-data -n psql-hb-dev-pool-01
```

Or use the Logic App's **Run trigger** in the portal (the dev schedule's start and stop apps).

### 3.2 Build and push the images to dev's registry

Start from a clean, committed tree. The tag is the commit sha.

```bash
git status --short                      # must print nothing
SHA=$(git rev-parse HEAD)
REG=acrhbdevac48.azurecr.io
az acr login --name acrhbdevac48

# The platform's images (one Dockerfile, one target each)
for t in api worker child-worker event-worker scheduler backup; do
  docker build --target "$t" -t "$REG/hb-$t:$SHA" backend && docker push "$REG/hb-$t:$SHA"
done
docker build --target runtime -t "$REG/hb-frontend:$SHA" frontend && docker push "$REG/hb-frontend:$SHA"

# The tenant runtime's images (slice 4)
STAGE=backend/docker/sandbox/stage      # gitignored
rm -rf "$STAGE"; mkdir -p "$STAGE/docfactory"
cp backend/docker/sandbox/{Dockerfile,requirements.txt,agent.py} "$STAGE/"
cp -R backend/scripts/seeds/default_entities/SeedDocumentFactory/scripts "$STAGE/docfactory/scripts"
docker build -t "$REG/hb-sandbox:$SHA" "$STAGE" && docker push "$REG/hb-sandbox:$SHA"
docker build -f backend/docker/checks/Dockerfile -t "$REG/hb-checks:$SHA" backend && docker push "$REG/hb-checks:$SHA"
docker build -t "$REG/hb-egress-proxy:$SHA" backend/docker/egress-proxy && docker push "$REG/hb-egress-proxy:$SHA"
docker build -t "$REG/hb-caddy-redis:$SHA" backend/docker/caddy-redis && docker push "$REG/hb-caddy-redis:$SHA"

# The App Controller: built on this release's API image
docker build -f backend/services/app_controller/Dockerfile --build-arg "BASE=$REG/hb-api:$SHA" \
  -t "$REG/hb-app-controller:$SHA" backend && docker push "$REG/hb-app-controller:$SHA"
```

That's all 12 images (the list in `deploy-azure.yml`'s `IMAGES`). A cold build on a laptop takes about 15 minutes. The chart expects every one of them under the same tag, so don't skip any. Images the release doesn't run today, such as the tenant runtime's on production, still have to exist for the copy in §3.5.

### 3.3 Deploy dev

```bash
helm --kube-context aks-hb-dev upgrade --install hb-platform infra/k8s/charts/hb-platform -n hb-platform \
  -f infra/k8s/charts/hb-platform/values-azure.yaml \
  -f infra/k8s/env/dev/hb-platform.yaml \
  --set global.imageRegistry=acrhbdevac48.azurecr.io \
  --set global.imageTag="$SHA" \
  --atomic --wait --timeout 20m
```

In a second terminal you can watch the migrations Job and the rollout:

```bash
kubectl --context aks-hb-dev -n hb-platform get jobs,pods -w
```

Then the same smoke test the pipeline runs:

```bash
kubectl --context aks-hb-dev -n hb-platform rollout status deploy/hb-api --timeout=5m
curl -fsS https://gateway.azdev.hirebuddha.com/api/v1/health
```

### 3.4 Check dev

As in §2.4. Don't continue to production until dev is right.

### 3.5 Copy dev's images to production (same digests)

```bash
SRC_ID=$(az acr show -n acrhbdevac48 --query id -o tsv)
for image in hb-api hb-worker hb-child-worker hb-event-worker hb-scheduler hb-backup hb-frontend \
             hb-sandbox hb-checks hb-egress-proxy hb-caddy-redis hb-app-controller; do
  az acr import --name acrhbprode7b3 --registry "$SRC_ID" \
    --source "$image:$SHA" --image "$image:$SHA" --force
done

# The digests must match (a spot check)
az acr repository show -n acrhbdevac48  --image "hb-api:$SHA" --query digest -o tsv
az acr repository show -n acrhbprode7b3 --image "hb-api:$SHA" --query digest -o tsv
```

`az acr import` copies the manifest as it is, so production runs byte-for-byte what dev ran.

### 3.6 Deploy production

Do the same check you'd do before approving in GitHub (§2.4). Then:

```bash
helm --kube-context aks-hb-prod upgrade --install hb-platform infra/k8s/charts/hb-platform -n hb-platform \
  -f infra/k8s/charts/hb-platform/values-azure.yaml \
  -f infra/k8s/env/prod/hb-platform.yaml \
  --set global.imageRegistry=acrhbprode7b3.azurecr.io \
  --set global.imageTag="$SHA" \
  --atomic --wait --timeout 20m

kubectl --context aks-hb-prod -n hb-platform rollout status deploy/hb-api --timeout=5m
curl -fsS https://gateway.azprod.hirebuddha.com/api/v1/health
```

Then check production as in §2.6.

### 3.7 After a manual release

1. **Push the commit you deployed.** The repository then matches what runs. The pipeline will build and deploy the same sha again, which is harmless: dev gets an identical release, and you can reject the production step.
2. **Write it down.** Note the date, sha, Helm revisions and why it was done by hand in `docs/phase14/06_implementation_status.md`, or in the release notes once Phase 14 is closed.
3. **Stop dev** if you started it outside its hours (§3.1).

---

## 4. Changes the pipeline does not make (both ways)

Do these **before** the release that needs them, in this order: Azure resources → Key Vault secrets → bootstrap → database roles → the release.

### 4.1 Azure resources (Bicep)

```bash
# The parameter file's header lists the variables it reads: dev also HB_SUFFIX,
# production also HB_BUDGET_EMAIL. The group ids are in infra/azure/env/<env>.env;
# the break-glass password must be the one already set: a new value changes the servers' admin password.
export HB_ADMINS_GROUP_ID=... HB_DEVELOPERS_GROUP_ID=... HB_PGADMINS_GROUP_ID=... \
       HB_PG_BREAK_GLASS_PASSWORD=...
az deployment sub what-if -l centralindia -f infra/azure/bicep/main.bicep -p infra/azure/env/dev.bicepparam
az deployment sub create  -l centralindia -f infra/azure/bicep/main.bicep -p infra/azure/env/dev.bicepparam
```

Read the **what-if** carefully. On production (`prod.bicepparam`), a resource it shows as "Delete" or "Modify" on a database, Key Vault or the cluster is a stop-and-think moment. After `create`, copy any new outputs (client ids, IPs) into `infra/azure/env/<env>.env` and the values files, and commit them.

### 4.2 Cluster bootstrap (`hb-bootstrap`)

```bash
export HB_ACME_EMAIL=<the Let's Encrypt contact address>
MSYS2_ARG_CONV_EXCL='/readyz' bash infra/k8s/bootstrap/install.sh dev     # Git Bash; on Linux/macOS drop the prefix
```

The script is idempotent. It installs or updates Envoy Gateway, cert-manager and the `hb-bootstrap` chart: namespaces, `sa-*` service accounts with their workload identities, cluster RBAC including the tenant runtime's, the Gateway and its certificates, and the OpenTelemetry Collector. Anything **cluster-scoped**, or in a namespace other than `hb-platform`/`hb-system`, belongs here, because the CI identity can't create it.

### 4.3 Key Vault secrets

```bash
# From a file or stdin, never typed on the command line (it lands in your shell history)
az keyvault secret set --vault-name kv-hb-dev-ac48  -n <name> --file <path-to-a-file-holding-the-value>
az keyvault secret set --vault-name kv-hb-prod-e7b3 -n <name> --file <path-to-a-file-holding-the-value>
```

Then add `{ name: <name>, alias: <SETTING_NAME> }` under `secrets.csi.objects` in the env's values file. Add it **only for an environment whose vault has the secret**: a missing secret stops every pod that mounts the secret store from starting. Settings that aren't secret go under `config:` in the values file.

### 4.4 Database roles and grants

The SQL in `infra/azure/sql/` runs as a member of the environment's PostgreSQL admins group (Entra sign-in), from a machine or pod that can reach the server. Run it before the release whose code needs the role.

---

## 5. Rolling back

Rolling forward (fix, commit, push) is usually best, because a rollback doesn't undo migrations. When production must go back now:

```bash
helm --kube-context aks-hb-prod -n hb-platform history hb-platform --max 5
helm --kube-context aks-hb-prod -n hb-platform rollback hb-platform <previous-good-revision> --wait --timeout 20m
curl -fsS https://gateway.azprod.hirebuddha.com/api/v1/health
```

* Rollback restores the previous chart, values and image tag. The images are still in the registry, since nothing deletes them.
* The database stays where the newer migrations took it. That's safe when §1.4 rule 1 was followed. If a migration was destructive, restore from the database's point-in-time backup instead. That's a separate, deliberate operation.
* The next pipeline run deploys whatever the branch holds, so revert the bad commit (`git revert <sha>`, push) or the rollback will be undone at the next push.
* To redeploy one specific older release, run §3.6 with `SHA=<that commit>`. Its images exist in both registries if it was ever promoted.

---

## 6. Checklists

**Before you push**
- [ ] §1.3 checks pass locally for what you touched
- [ ] Migrations are backward compatible and tested up/down/up
- [ ] New secrets exist in the Key Vault(s) and new Azure or bootstrap changes are applied (§4)
- [ ] The rendered production manifests changed only in the way you meant
- [ ] No production approval is pending, or you're fine queueing behind it (§2.7)
- [ ] Dev is up (working hours, or started by hand)

**Before you approve production**
- [ ] The run's `dev` job is green, including the smoke test
- [ ] Dev's health is `ok` and the change works on dev
- [ ] For a large change: the relevant manual test-plan sections passed on dev

**After production**
- [ ] Production's health is `ok`; sign in and do a quick check
- [ ] `helm history` shows the new revision `deployed`, and the pods run the new tag with no restarts
- [ ] Anything manual is written down (§3.7), and dev is stopped if you started it out of hours

---

## 7. Quick reference

| | Command |
|---|---|
| Last runs | `gh run list --workflow deploy-azure --limit 5` |
| Follow a run | `gh run watch <run-id>` |
| A run's logs | `gh run view <run-id> --log` |
| Start the workflow by hand | `gh workflow run deploy-azure --ref roadmap-development-defect-fixes` |
| Release history | `helm --kube-context aks-hb-<env> -n hb-platform history hb-platform --max 5` |
| Pods and their images | `kubectl --context aks-hb-<env> -n hb-platform get pods -o custom-columns=N:.metadata.name,IMG:.spec.containers[0].image` |
| Health | `curl -fsS https://gateway.az<env>.hirebuddha.com/api/v1/health` |
| Is dev running | `az aks show -g rg-hb-dev-aks -n aks-hb-dev --query powerState.code -o tsv` |

**Files**
- `.github/workflows/ci.yml`: the checks
- `.github/workflows/deploy-azure.yml`: images, dev, prod
- `.github/actions/rollout/action.yml`: the Helm rollout and smoke test both environments use
- `infra/k8s/charts/hb-platform/`: the release chart (`templates/migrations-job.yaml` is the migrations hook)
- `infra/k8s/charts/hb-bootstrap/` and `infra/k8s/bootstrap/install.sh`: the cluster bootstrap
- `infra/azure/bicep/` and `infra/azure/env/`: the Azure resources and each environment's names
- `docs/phase14/04_azure_environment_setup.md`: how the environments were built (identities, federation, Key Vault)
- `docs/how-to/PRODUCTION_MANUAL_TEST_PLAN.md`: what to test by hand
