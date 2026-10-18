# HireBuddha backend images (Phase 14 WS1 1.1). One build, one target per process:
#
#   docker build --target api          -t hb-api .          # FastAPI on :8000
#   docker build --target worker       -t hb-worker .       # arq: default queue + crons
#   docker build --target child-worker -t hb-child-worker . # arq: queue "children"
#   docker build --target event-worker -t hb-event-worker . # arq: queue "events" (WS3 router)
#   docker build --target scheduler    -t hb-scheduler .    # WS3 tenant scheduler
#   docker build --target data-api     -t hb-data-api .     # WS4 Data API on :8080, one per business
#   docker build --target backup       -t hb-backup .       # weekly pg_dump exports (D45)
#   docker build --target dev          -t hb-dev .          # local: --reload, used by docker-compose
#
# The images hold no secrets and no configuration: settings come from the
# environment (the Key Vault CSI driver in AKS, .env locally). They run as a
# non-root user and work with a read-only root filesystem; /tmp and /app/var
# are the writable paths (emptyDir volumes in the Helm chart).

FROM python:3.12-slim AS builder

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_VERSION=2.5.1 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="$POETRY_HOME/bin:$PATH"

# Copy dependencies
COPY pyproject.toml poetry.lock* ./

# Install the runtime dependencies only (no pytest, ruff, mypy in an image)
RUN poetry install --only main --no-root --no-ansi

# Runtime stage
FROM python:3.12-slim AS runtime

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    HOME=/tmp

# Copy virtualenv from builder
COPY --from=builder /app/.venv ./.venv

# What the tools need from the OS (TL-66): WeasyPrint renders with Pango
# (pdf_generator); headless_browser drives Chromium, which runs in this image
# even under the container sandbox runtime. The browsers go to a shared path
# so the non-root user finds them.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core tzdata \
    && /app/.venv/bin/playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# A fixed non-root user (Kubernetes runAsUser matches it).
RUN groupadd --system --gid 10001 hb \
    && useradd --system --uid 10001 --gid hb --home-dir /tmp --shell /usr/sbin/nologin hb

# Copy application code
COPY --chown=hb:hb . .

# Local-disk storage and sandbox workspaces, when a deployment uses them.
RUN mkdir -p /app/var /app/artifact /app/uploads && chown -R hb:hb /app/var /app/artifact /app/uploads

USER 10001:10001

FROM runtime AS api
EXPOSE 8000
# Forwarded headers are trusted only from the edge's addresses (FORWARDED_ALLOW_IPS,
# set by the chart to the ingress's range; P-10).
CMD ["sh", "-c", "exec uvicorn src.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]

FROM runtime AS worker
EXPOSE 9101
CMD ["python", "-m", "arq", "src.ai.worker.WorkerSettings"]

FROM runtime AS child-worker
EXPOSE 9102
CMD ["python", "-m", "arq", "src.ai.worker.ChildWorkerSettings"]

FROM runtime AS event-worker
# Automation events: the router decides which triggers start runs (tech spec §7.8).
EXPOSE 9103
CMD ["python", "-m", "arq", "src.ai.worker.EventWorkerSettings"]

FROM runtime AS scheduler
# The tenant scheduler (tech spec §7.7): fires schedules and timers from the
# control database's time index.
CMD ["python", "-m", "src.automation.scheduler"]

FROM runtime AS data-api
# The Data API alone (tech spec §9.1): one Deployment per business, which
# DATA_API_TENANT_KEY pins; /healthz and /readyz for the probes.
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn src.data_api.main:app --host 0.0.0.0 --port 8080 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]

FROM runtime AS backup
# Weekly database exports (decision D45): pg_dump must be the servers' major
# version (16) or newer, which Debian's own client is not; the PostgreSQL
# project's apt repository provides it.
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-common ca-certificates \
    && /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
    && rm -rf /var/lib/apt/lists/*
ENV PG_DUMP_PATH=/usr/lib/postgresql/16/bin/pg_dump
USER 10001:10001
CMD ["python", "-m", "scripts.backup_databases"]

FROM runtime AS dev
USER root
EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
