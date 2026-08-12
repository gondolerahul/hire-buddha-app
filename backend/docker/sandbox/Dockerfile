# hb-sandbox — the per-tenant execution image for the Phase 12 `02` ContainerRuntime.
#
# A single base image shared by the sandbox_code, terminal, and headless_browser
# tools (and the `03` video tool's ffmpeg). It bakes in every interpreter and
# binary those tools shell out to so a tenant container needs no network at run
# time:
#
#   * Python 3 + the Document Factory libraries (docx/xlsx/pdf generation)
#   * Node + pptxgenjs (the JS pptx path in sandbox_code)
#   * Playwright + Chromium (headless_browser)
#   * ffmpeg (video) and LibreOffice headless (document rendering)
#   * the Document Factory scripts, baked in at /opt/docfactory/scripts
#     (replacing the host symlink provisioning in sandbox_provision.py)
#
# Pinned by digest, not tag — see build.sh, which records the digest in
# image.pin. The image runs as a non-root user; the ContainerRuntime adds the
# kernel-level isolation (read-only root, dropped caps, default-deny network,
# cpu/memory/pids limits) at `docker run` time.
#
# The base is Microsoft's Playwright image so the Chromium build always matches
# the pinned Playwright version (1.58.0); bumping Playwright means bumping both.
FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    NODE_PATH=/opt/sandbox/node_modules \
    HOME=/tmp

# System binaries the tools shell out to. The Playwright *python* base ships
# Chromium but not the Node CLI, so install nodejs+npm here (the JS pptx path).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libreoffice-calc libreoffice-impress libreoffice-writer \
        fonts-liberation \
        nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# Python document-generation libraries (the Document Factory deps).
COPY requirements.txt /opt/sandbox/requirements.txt
RUN pip install --no-cache-dir -r /opt/sandbox/requirements.txt

# Node libraries (the JS pptx path).
RUN mkdir -p /opt/sandbox \
    && cd /opt/sandbox \
    && npm install --no-audit --no-fund pptxgenjs@^4.0.1 \
    && npm cache clean --force

# The Document Factory scripts, baked in (was a host symlink in
# sandbox_provision.py; the ContainerRuntime sets SANDBOX_SHARED_DIRS to point
# the tools at this path instead).
COPY docfactory/scripts /opt/docfactory/scripts

# Non-root tenant user. /workspace is where the ContainerRuntime bind-mounts the
# tenant's durable directory; both it and the user's HOME must be writable.
RUN groupadd --gid 10001 sandbox \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/sandbox sandbox \
    && mkdir -p /workspace \
    && chown -R sandbox:sandbox /workspace /opt/sandbox

ENV HOME=/home/sandbox
USER sandbox
WORKDIR /workspace

# The container is a long-lived, idle-by-default workspace: the ContainerRuntime
# execs into it per call. Sleep forever so it stays up between calls (the
# TenantSandboxManager pauses/reaps it on its own TTLs).
CMD ["sleep", "infinity"]
