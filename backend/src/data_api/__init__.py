"""The Data API (Phase 14 WS4, tech spec §9): a business's records over HTTP,
for its agents (run tokens), its apps (app keys), outside systems and the
HireBuddha screens (user tokens).

* ``model``   — SQLAlchemy Core tables built from the active blueprint;
* ``records`` — reads, writes (row + audit + ``record.*`` event in one
  transaction), filters, paging, reports;
* ``tokens``  — run and user tokens, app keys;
* ``app``     — the FastAPI app (``python -m uvicorn src.data_api.main:app``;
  the platform API also mounts it under ``/data``).

The spec places the service at ``backend/services/data_api``; it lives under
``src/`` like every other package so imports and images stay one tree.
"""
