# Phase 12 — Step-by-Step Operations Implementation Guide

This guide details the step-by-step procedures to implement and verify the remaining operations-only items in production. These items are code-complete but require production credentials, registries, or running front-end environments.

---

## 1. `02` S7 — Sandbox Container Go-Live

### Goal
Deploy the isolated, persistent per-tenant Docker sandbox runtime (`hb-sandbox`) and the egress allow-list proxy (`hb-egress-proxy`) to production, and enable them via a canary rollout.

### Step 1.1: Image CVE Scan
Run container vulnerability scans to ensure the sandbox base image is secure before launching it.
1. Locate the pinned sandbox image digest in [image.pin](file:///home/rahul/workspace/hb-proto-3/backend/docker/sandbox/image.pin):
   * `sha256:c732b8e97e247c560f72fc89de0e64b45930cc01fd1674f7ae7d5ea1f9aac765`
2. Install Trivy (or use your preferred scanner):
   ```bash
   sudo apt-get install trivy
   ```
3. Run the vulnerability scan against the sandbox image:
   ```bash
   trivy image hb-sandbox@sha256:c732b8e97e247c560f72fc89de0e64b45930cc01fd1674f7ae7d5ea1f9aac765
   ```
4. Build the egress proxy image locally and scan it:
   ```bash
   docker build -t hb-egress-proxy:local backend/docker/egress-proxy
   trivy image hb-egress-proxy:local
   ```
5. Triage any `CRITICAL` or `HIGH` vulnerabilities before pushing to production registries.

### Step 1.2: Registry Publish
Publish the scanned images to your production container registry (e.g., Google Artifact Registry, AWS ECR).
1. Authenticate your local Docker client to the registry (example for Google Artifact Registry):
   ```bash
   gcloud auth configure-docker <region>-docker.pkg.dev
   ```
2. Tag both images for the remote registry:
   ```bash
   docker tag hb-sandbox:local <region>-docker.pkg.dev/<project>/<repo>/hb-sandbox:0.1.0
   docker tag hb-egress-proxy:local <region>-docker.pkg.dev/<project>/<repo>/hb-egress-proxy:0.1.0
   ```
3. Push the images:
   ```bash
   docker push <region>-docker.pkg.dev/<project>/<repo>/hb-sandbox:0.1.0
   docker push <region>-docker.pkg.dev/<project>/<repo>/hb-egress-proxy:0.1.0
   ```
4. Retrieve the exact pushed digests to lock down in configuration:
   ```bash
   docker inspect --format='{{index .RepoDigests 0}}' <region>-docker.pkg.dev/<project>/<repo>/hb-sandbox:0.1.0
   docker inspect --format='{{index .RepoDigests 0}}' <region>-docker.pkg.dev/<project>/<repo>/hb-egress-proxy:0.1.0
   ```
5. Update production settings / environment variables with the registry digests:
   * `SANDBOX_IMAGE=<registry-path>/hb-sandbox@sha256:...`
   * `SANDBOX_EGRESS_IMAGE=<registry-path>/hb-egress-proxy@sha256:...`

### Step 1.3: Canary Rollout
1. Enable the egress network proxy globally for worker processes:
   ```bash
   export SANDBOX_EGRESS_PROXY_ENABLED=true
   export SANDBOX_EGRESS_ALLOWLIST="googleapis.com,google.com" # update with required endpoints
   ```
2. Flip the feature flag `sandbox.container_runtime_enabled` on a **per-company basis** in the database:
   ```sql
   INSERT INTO feature_flags (id, company_id, entity_id, flag_key, enabled, created_at, updated_at)
   VALUES (
     gen_random_uuid(),
     '<target-company-uuid>',
     NULL,
     'sandbox.container_runtime_enabled',
     true,
     now(),
     now()
   )
   ON CONFLICT (flag_key, company_id) WHERE company_id IS NOT NULL AND entity_id IS NULL
   DO UPDATE SET enabled = true, updated_at = now();
   ```
3. Monitor logs for the targeted company:
   * Verify that containers spawn, pause, and reap cleanly.
   * Verify resource attribution logs written to the database under the `SANDBOX` SKU.
4. Once stable, toggle the default to `True` in [feature_flags.py](file:///home/rahul/workspace/hb-proto-3/backend/src/ai/core/feature_flags.py#L102) or insert a global DB flag (`company_id IS NULL`).

---

## 2. `04` — Publish `cortex-memory` to PyPI

### Goal
Move the standalone `cortex_memory` package out of the repository into its own GitHub repo, publish it to PyPI, and consume it via Poetry in the main platform.

> [!IMPORTANT]
> The package **must be copied** into the new GitHub repo and successfully pushed **before** it is removed from `hb-proto-3`. Do not `rm -rf` until the PyPI upload is confirmed.

### Step 2.1: Clone the New Repo and Copy the Package

The new GitHub repo (`github.com/gondolerahul/cortex-memory`) has already been created.

1. Clone it to a location **outside** of `hb-proto-3`:
   ```bash
   cd ~
   git clone https://github.com/gondolerahul/cortex-memory.git
   cd cortex-memory
   ```
2. Copy the package contents from `hb-proto-3` into the new repo root:
   ```bash
   cp -R ~/workspace/hb-proto-3/backend/cortex_memory/. .
   ```
3. Verify the structure looks correct (pyproject.toml should be at the repo root):
   ```bash
   ls pyproject.toml README.md LICENSE cortex_memory/ tests/
   ```

### Step 2.2: Commit and Push to GitHub

1. Stage all files and make the initial commit:
   ```bash
   git add .
   git commit -m "chore: initial publish of cortex-memory package (migrated from hb-proto-3)"
   ```
2. Push to GitHub:
   ```bash
   git push origin main
   ```
3. Confirm the repo at `https://github.com/gondolerahul/cortex-memory` shows the full package source before continuing.

### Step 2.3: Build and Publish to PyPI

All commands below run inside `~/cortex-memory` (the standalone repo root, **not** inside `hb-proto-3`).

1. Install build tools:
   ```bash
   pip install build twine
   ```
2. Build the source distribution and wheel:
   ```bash
   python -m build
   ```
3. Verify `dist/` contains both a `.tar.gz` and a `.whl` before uploading:
   ```bash
   ls dist/
   ```
4. Upload to PyPI (supply your PyPI API token when prompted):
   ```bash
   twine upload dist/*
   ```
5. Confirm the package is live at `https://pypi.org/project/cortex-memory/`.

### Step 2.4: Drop Local Copy from `hb-proto-3` and Reference PyPI Package

> [!CAUTION]
> Only proceed once Step 2.3 is fully confirmed — the package must be live on PyPI and the GitHub repo must have the full source.

1. Remove the local source folder from the main platform repo:
   ```bash
   cd ~/workspace/hb-proto-3
   rm -rf backend/cortex_memory/
   ```
2. Open [pyproject.toml](file:///home/rahul/workspace/hb-proto-3/backend/pyproject.toml) and add the PyPI dependency:
   ```toml
   [tool.poetry.dependencies]
   hb-cortex-memory = "0.1.0"
   ```
3. Regenerate Poetry locks and install the dependency:
   ```bash
   poetry update hb-cortex-memory
   ```
4. Run tests to verify that imports now correctly point to the PyPI package:
   ```bash
   poetry run pytest tests/unit
   ```
5. Commit the removal and lock-file update:
   ```bash
   git add backend/pyproject.toml poetry.lock
   git commit -m "chore: replace local cortex_memory with PyPI package hb-cortex-memory==0.1.0"
   git push origin phase12/stage1-consolidation
   ```

> [!NOTE]
> Review [04_cortex_package.md](file:///home/rahul/workspace/hb-proto-3/docs/phase12/plans/04_cortex_package.md) to ensure K1–K7 decisions remain locked:
> * **K1**: Package name is `hb-cortex-memory`; imported as `cortex_memory`.
> * **K2**: Licensed under Apache-2.0.
> * **K5**: Database foreign keys are represented as opaque nullable UUIDs in the package models.
> * **K6**: Task classification stays on the host side (package remains memory-only).

---

## 3. `06` GA Canary Flips

### Goal
Progressively enable Meta-Agent v5 capabilities in production, ensuring telemetry is healthy.

### Step 3.1: Pre-GA Database Migration (Backfill)
Before shifting routing to the Architecture Board, run the migration to preserve meta-cognition settings for existing entities.
1. Run the backfill script:
   ```bash
   cd backend
   .venv/bin/python -m src.ai.meta.meta_cognition_migration
   ```
2. Verify in the logs that any pre-existing `AGENT` and `PROCESS` entities have explicit `registry_search` and `self_modification` capability booleans populated.

### Step 3.2: Canary Rollout Sequence
For each capability, enable it for one company in the database `feature_flags` table (using `flag_key` and the target `company_id`):

1. **Board Routing (`meta_agent.board_routing`)**:
   * *Action*: Flipped ON. Ensure `meta_cognition_migration` has completed first.
   * *Telemetry*: Watch board promotion reject rates (target `R-PRG-8` ≤30% over 7 days).
2. **Tool Synthesis (`meta_agent.tool_synthesis_enabled`)**:
   * *Action*: Flipped ON. (Requires Container Sandbox from Item 1).
   * *Telemetry*: Ensure the first N tools are flagged as `DRAFT` in the `ToolRegistry` and require manual HITL promotion.
3. **Curator Consolidation (`meta_agent.curator_consolidation_enabled`)**:
   * *Action*: Flipped ON.
   * *Telemetry*: Verify merge plans generated for duplicate entities, ensuring HITL approval and audit logs are recorded.
4. **Trust-Score Learning (`memory.trust_score_learning`)**:
   * *Action*: Flipped ON.
   * *Telemetry*: Verify the `source_trust_scores` schema updates dynamically.
5. **LLM Strategist (`agent_loop.llm_strategist_enabled`)**:
   * *Action*: Run comparative evaluation runs against deterministic rules on `tests/eval` before enabling.

---

## 4. P-O3 — Frontend verification (Storybook / Lighthouse / Playwright)

### Goal
Verify frontend changes corresponding to the Phase 11 re-branding (re-prefixing `P11` identifiers to clean `agentKernel` namespaces).

### Step 4.1: Component Validation
1. Run Storybook to verify that components render correctly:
   ```bash
   npm run storybook
   ```
2. Run end-to-end integration tests using Playwright:
   ```bash
   npx playwright test
   ```
3. Audit performance and accessibility using Lighthouse (ensure scores are above 90).
4. Verify that the redirect route rules `/admin/agent-kernel/*` redirect user traffic appropriately.

---

## 5. C4 G4 Flag Soak

### Goal
Address the Stage-0 telemetry soak for the old execution engine removal.

### Step 5.1: Monitoring and Validation
* *Action*: The deletion of the legacy `execute_run` engine has already landed directly in code. The G4 soak is a no-op at code level.
* *Verification*:
  1. Monitor server logs for any invocations of `execute_run` (should be zero).
  2. Confirm that `resume_parent_run` and `resume_execution` arq jobs are processing loop states normally.
  3. Keep watch on the `suspend_requested` event telemetry for parent/child workflows.
