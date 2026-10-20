"""API-17, API-I1: docs/reference/api-routes.md lists every route the app serves, or this fails.

A full path chains three prefixes, so the decorator misleads, and the
reference's hand-written tables drifted from the code. The census there is
generated from the app (``scripts/route_census.py``); a route added, moved or
removed without regenerating it fails here.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "route_census.py"


def _census():
    spec = importlib.util.spec_from_file_location("route_census", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_reference_lists_every_route_the_app_serves():
    census = _census()
    documented = census.doc_block(census.DOC.read_text(encoding="utf-8"))
    assert documented, "api-routes.md has lost its route-census block"
    assert documented == census.table(), (
        "api-routes.md is not the app's route table: "
        "run `python scripts/route_census.py --write` from backend/")


def test_a_guard_reads_the_route_dependencies():
    census = _census()
    rows = {(path, method): who for path, method, who, _module, _dep in census.rows()}
    assert rows[("/api/v1/ai/admin/feature_flags/invalidate", "POST")] == "roles: app_admin"
    assert rows[("/api/v1/ai/executions/{execution_id}/stream", "GET")] == "URL token"
    assert rows[("/internal/event", "POST")] == "internal token"
    assert rows[("/stream/audio", "WS")] == "own handshake"
