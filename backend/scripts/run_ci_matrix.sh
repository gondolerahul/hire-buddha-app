#!/usr/bin/env bash
# Phase 11 Track 14 — CI matrix runner.
#
# Lanes:
#   fast      — every PR. Unit + layout lint + fast integration tests.
#   nightly   — chaos + parity + regression. Skipped on PR.
#   migration — Alembic upgrade head + downgrade -1 + upgrade head.
#
# Usage:
#   scripts/run_ci_matrix.sh fast
#   scripts/run_ci_matrix.sh nightly
#   scripts/run_ci_matrix.sh migration
#   scripts/run_ci_matrix.sh all     # run every lane sequentially
#
# Environment:
#   DATABASE_URL  — required for integration / chaos lanes (Postgres).
#   The script never starts containers; CI/Docker Compose is expected
#   to set the URL.

set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PY:-.venv/bin/python}"
PYTEST="${PYTEST:-$PY -m pytest}"
LANE="${1:-fast}"

bold() { printf "\033[1m== %s ==\033[0m\n" "$*"; }

run_layout_lint() {
    bold "layout lint"
    $PY scripts/lint_ai_layout.py
}

run_typecheck() {
    bold "mypy --strict gate"
    $PY scripts/typecheck_ai.py
}

run_unit() {
    bold "unit tests"
    $PYTEST tests/unit/ -q
}

run_integration_fast() {
    # tests/integration without the slow tests and the Docker-image tests
    # (those need the built images: their own job). Per the test strategy
    # doc, "fast" integration tests must complete in well under a minute on
    # a clean CI runner.
    bold "integration (fast)"
    $PYTEST tests/integration/ -q -m "not (slow or docker)"
}

run_chaos() {
    bold "chaos suite"
    $PYTEST tests/chaos/ -q -m chaos
}

run_parity() {
    bold "parity suite"
    $PYTEST tests/parity/ -q
}

run_regression() {
    bold "regression suite"
    $PYTEST tests/regression/ -q
}

run_migration_roundtrip() {
    bold "migration trees up → down → up roundtrip"
    .venv/bin/python -m src.common.tenancy.migrate control
    .venv/bin/alembic -n tenant_platform -x schema=public downgrade -1
    .venv/bin/alembic downgrade -1
    .venv/bin/python -m src.common.tenancy.migrate control
}

case "$LANE" in
    fast)
        run_layout_lint
        run_typecheck
        run_unit
        run_integration_fast
        ;;
    nightly)
        run_parity
        run_regression
        run_chaos
        ;;
    migration)
        run_migration_roundtrip
        ;;
    chaos)
        run_chaos
        ;;
    all)
        run_layout_lint
        run_typecheck
        run_unit
        run_integration_fast
        run_chaos
        run_parity
        run_regression
        run_migration_roundtrip
        ;;
    *)
        echo "Unknown lane: $LANE" >&2
        echo "Usage: $0 {fast|nightly|migration|chaos|all}" >&2
        exit 2
        ;;
esac

bold "lane '$LANE' done"
