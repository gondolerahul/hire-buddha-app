"""PO-10: a router that fails to import is reported on GET /api/v1/health.

Before, main.py caught the ImportError, logged a warning and moved on, so the
router's whole feature area answered 404 with nothing in any API response to
say why.
"""
import sys
import types

import httpx
from fastapi import APIRouter, FastAPI

from src.common.router_mounts import health_router, mount_optional


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(health_router)
    return app


async def _get(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def test_a_router_that_imports_is_mounted(monkeypatch):
    router = APIRouter()

    @router.get("/ping")
    async def ping():
        return {"pong": True}

    module = types.ModuleType("po10_good_router")
    module.router = router  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "po10_good_router", module)

    app = _app()
    assert mount_optional(app, "po10_good_router", prefix="/api/v1") is True

    assert (await _get(app, "/api/v1/ping")).json() == {"pong": True}
    body = (await _get(app, "/api/v1/health")).json()
    assert (body["status"], body["unmounted_routers"]) == ("ok", [])


async def test_a_missing_module_is_reported_and_the_app_still_boots():
    app = _app()
    assert mount_optional(app, "src.po10_no_such_router") is False

    body = (await _get(app, "/api/v1/health")).json()
    assert body["status"] == "degraded"
    assert body["unmounted_routers"] == [
        {
            "router": "src.po10_no_such_router",
            "error": "ModuleNotFoundError: No module named 'src.po10_no_such_router'",
        }
    ]


async def test_a_broken_import_inside_the_module_is_reported_without_file_paths(tmp_path, monkeypatch):
    (tmp_path / "po10_broken_router.py").write_text("from os import no_such_name\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "po10_broken_router", raising=False)

    app = _app()
    mount_optional(app, "po10_broken_router")
    mount_optional(app, "src.po10_no_such_router")

    body = (await _get(app, "/api/v1/health")).json()
    assert body["status"] == "degraded"
    assert [r["router"] for r in body["unmounted_routers"]] == [
        "po10_broken_router",
        "src.po10_no_such_router",
    ]
    error = body["unmounted_routers"][0]["error"]
    assert error == "ImportError: cannot import name 'no_such_name' from 'os'"
    assert "\\" not in error and "/" not in error


async def test_the_platform_app_mounts_every_optional_router(monkeypatch):
    """Also a tripwire: any optional router that stops importing fails this test."""
    # Without this the import installs an OTLP span exporter that retries
    # against localhost:4317 for about a minute when the test session exits.
    monkeypatch.setattr("src.common.telemetry.setup_telemetry", lambda app: None)
    from src.main import app

    response = await _get(app, "/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["unmounted_routers"]) == ("ok", [])
