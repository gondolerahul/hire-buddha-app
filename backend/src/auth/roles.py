"""The six platform roles and who may grant which.

``users.role`` is a plain string column; this enum is the list of values it may
hold. Request schemas type their ``role`` fields with it, so an unknown string
(``"tenant-admin"``, ``"superuser"``) is a 422 instead of a row nothing matches.
"""
from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    APP_ADMIN = "app_admin"
    APP_USER = "app_user"
    PARTNER_ADMIN = "partner_admin"
    PARTNER_USER = "partner_user"
    TENANT_ADMIN = "tenant_admin"
    TENANT_USER = "tenant_user"


# Roles that manage users: create them, edit them, deactivate them.
USER_ADMIN_ROLES: frozenset[Role] = frozenset({Role.APP_ADMIN, Role.PARTNER_ADMIN, Role.TENANT_ADMIN})

_ASSIGNABLE: dict[Role, frozenset[Role]] = {
    Role.APP_ADMIN: frozenset(Role),
    Role.PARTNER_ADMIN: frozenset({Role.PARTNER_ADMIN, Role.PARTNER_USER, Role.TENANT_ADMIN, Role.TENANT_USER}),
    Role.TENANT_ADMIN: frozenset({Role.TENANT_ADMIN, Role.TENANT_USER}),
}


def assignable_roles(assigner_role: str) -> frozenset[Role]:
    """The roles a user with ``assigner_role`` may give to someone else."""
    try:
        return _ASSIGNABLE.get(Role(assigner_role), frozenset())
    except ValueError:
        return frozenset()
