"""One role guard, typed roles, and app_admin never locked out (AU-17, AU-18, AU-21).

There were five guard styles — ``RoleChecker`` plus two different
``_require_admin`` helpers, ``_require_app_admin`` and ``_require_roles`` — with
role names as free strings (a typo made a guard that allowed nobody) and
``app_admin`` allowed only where a list remembered it. The route-table checks
below walk the real app, so a new route inherits them.
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from src.auth.dependencies import RoleChecker
from src.auth.roles import ADMIN_ROLES, Role

SRC = Path(__file__).resolve().parents[2] / "src"


def _user(role: str):
    return SimpleNamespace(role=role)


def test_app_admin_passes_a_guard_that_does_not_list_it():
    guard = RoleChecker([Role.TENANT_ADMIN])
    assert guard(_user("app_admin")).role == "app_admin"
    assert guard(_user("tenant_admin")).role == "tenant_admin"


@pytest.mark.parametrize("role", ["tenant_user", "partner_admin", "app_user"])
def test_other_roles_are_refused(role):
    with pytest.raises(HTTPException) as exc:
        RoleChecker([Role.TENANT_ADMIN])(_user(role))
    assert exc.value.status_code == 403


def test_a_misspelt_role_fails_when_the_guard_is_built():
    with pytest.raises(ValueError):
        RoleChecker(["tenant-admin"])


def test_the_hand_rolled_guards_are_gone():
    pattern = re.compile(r"def _require_(admin|app_admin|roles)\b")
    offenders = [str(p.relative_to(SRC)) for p in SRC.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


def _guards():
    """(method path, allowed roles) for every route guarded by a RoleChecker."""
    from src.main import app

    def walk(dependant):
        for dep in dependant.dependencies:
            if isinstance(dep.call, RoleChecker):
                yield dep.call
            yield from walk(dep)

    found = {}
    for route in app.routes:
        if isinstance(route, APIRoute):
            for guard in walk(route.dependant):
                for method in route.methods:
                    found[f"{method} {route.path}"] = guard.allowed_roles
    return found


def test_every_guard_admits_app_admin_and_only_real_roles():
    guards = _guards()
    assert len(guards) > 40
    for route, roles in guards.items():
        assert Role.APP_ADMIN in roles, route
        assert all(isinstance(r, Role) for r in roles), route


@pytest.mark.parametrize("route,roles", [
    ("GET /api/v1/ai/admin/admin/kpi/runs", ADMIN_ROLES),
    ("GET /api/v1/ai/admin/meta/skill_candidates", ADMIN_ROLES),
    ("POST /api/v1/cron/daily-credits", {Role.APP_ADMIN}),
    ("GET /api/v1/config/task-defaults", {Role.APP_ADMIN}),
    ("GET /api/v1/reports/analytics/data-growth", {Role.APP_ADMIN, Role.APP_USER}),
    ("GET /api/v1/reports/analytics/tenant-health", {Role.APP_ADMIN, Role.PARTNER_ADMIN, Role.PARTNER_USER}),
    ("POST /api/v1/users", ADMIN_ROLES),
    ("GET /api/v1/companies/partners", {Role.APP_ADMIN}),
    ("GET /api/v1/reports/costing", {Role.APP_ADMIN}),
])
def test_converted_routes_keep_their_roles(route, roles):
    assert _guards()[route] == frozenset(roles)
