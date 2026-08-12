# `hb-sandbox` — the per-tenant sandbox image (Phase 12 `02` S3)

A single base image that hosts every interpreter/binary the sandbox tools
(`sandbox_code`, `terminal`, `headless_browser`) and the `03` video tool shell
out to, so a tenant container needs no network at run time:

| Layer | Contents |
|-------|----------|
| Base | `mcr.microsoft.com/playwright/python:v1.58.0-noble` (Python 3 + Node + Chromium, pinned to the host's Playwright 1.58.0) |
| Python | Document Factory libs — see [`requirements.txt`](./requirements.txt) |
| Node | `pptxgenjs` (the JS pptx path in `sandbox_code`) |
| System | `ffmpeg`, LibreOffice headless, Liberation fonts |
| Scripts | Document Factory scripts baked at `/opt/docfactory/scripts` |
| User | non-root `sandbox` (uid 10001); `/workspace` is the bind-mount point |

The image carries **no isolation policy of its own** — the
[`ContainerRuntime`](../../src/ai/tools/sandbox/container_runtime.py) applies
read-only root, `--cap-drop ALL`, `--network none`, and cpu/memory/pids limits
at `docker run` time.

## Build & pin

```bash
cd backend/docker/sandbox
./build.sh                       # builds hb-sandbox:local, writes image.pin
```

`build.sh` stages a small build context (this Dockerfile + requirements + the
Document Factory scripts copied from `backend/scripts/.../SeedDocumentFactory/scripts`)
so the whole backend tree is never shipped as context. It records the built
image's digest in `image.pin`.

## Use it

The container runtime is **OFF by default** (`SubprocessRuntime` stays the
dev/CI default and the production rollback path). To turn it on for a worker/API
process:

```bash
export SANDBOX_CONTAINER_RUNTIME_ENABLED=true
export SANDBOX_IMAGE=hb-sandbox:local      # or the digest in image.pin
```

Per-company canary is done via the `sandbox.container_runtime_enabled` feature
flag (DB/`AI_FLAG_` env) instead of the process-wide settings flag.

## Publish (deliberate ops step — not automated)

```bash
docker tag hb-sandbox:local <registry>/hb-sandbox:<date>
docker push <registry>/hb-sandbox:<date>
# then pin SANDBOX_IMAGE to the registry digest (<registry>/hb-sandbox@sha256:...)
```

## CI / tests

CI never builds or needs this image — the test suite rides `SubprocessRuntime`.
The `ContainerRuntime` integration tests
(`tests/integration/test_container_runtime.py`) are **Docker-gated** and run
against a lightweight `python:3.12-slim` image (not this heavy one), so they
stay fast; they skip entirely when Docker is unavailable.

## Security review gate

Per [`plans/02_sandbox_browser_terminal.md`](../../../docs/phase12/plans/02_sandbox_browser_terminal.md)
§6, the container escape surface, egress policy, and secret handling need a
dedicated security review **before** the canary flip. Treat the default-ON flip
as a release gate.
