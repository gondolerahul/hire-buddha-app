# hb-checks — a promotion's checks on AKS (Phase 14 WS6 6.3, tech spec §11.2):
# the check suite (src/code_lanes/check_suite.py, standard library only) with
# the tools it uses when present: gitleaks, semgrep, pip-audit, npm, pytest.
# Run as a Kubernetes Job on the sandbox pool; it fetches the files from a
# signed URL and prints one "HB-CHECKS <json>" line.
#   docker build -f docker/checks/Dockerfile -t hb-checks:local .   (from backend/)
FROM python:3.12-slim

ARG GITLEAKS_VERSION=8.21.2
ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 HOME=/tmp

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl nodejs npm git \
    && curl -fsSL "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
       | tar -xz -C /usr/local/bin gitleaks \
    && pip install "semgrep==1.97.0" "pip-audit==2.7.3" "pytest>=8,<9" \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY src/code_lanes/check_suite.py /opt/hb/check_suite.py
RUN useradd --uid 10001 --no-create-home checks
USER 10001
ENTRYPOINT ["python3", "/opt/hb/check_suite.py"]
