"""The control and tenant declarative bases (Phase 14 WS2 2.2, tech spec §5.3, Appendix A).

Every ORM table belongs to exactly one plane:

* **control** — shared by every tenant, in the control database: identity,
  companies, billing, the platform catalogues, routing indexes (phone numbers,
  webhook endpoints) and the tenant directory;
* **tenant** — one tenant's own data, in that tenant's database, schema
  ``platform``: agents, runs, traces, approvals, memory, documents, artifacts,
  campaigns, calls and sessions.

A model says which by its base: ``class ExecutionRun(TenantBase)``.

Both bases share the one registry and ``MetaData`` the models have always had
(``src.common.database.Base``), and the tables are unqualified: the shared
database of ``TENANCY_MODE=single`` keeps every table in ``public``, a tenant
database its tables in ``platform`` (its connections search it first). The
plane is recorded on each table (``Table.info["plane"]``): each of the two
migration trees (2.7, ``migrations/envlib.py``) compares its plane's tables,
and a split-mode session sends each class to its plane's database
(``session.py``).

No foreign key or ORM relationship crosses the planes (2.3, tech spec §5.3
rule 2): a column that names a row of the other plane (a run's ``company_id``,
a usage row's ``run_id``, a number's ``agent_id``) is a plain UUID marked with
``refers_to()``, and services keep what the key gave — the id is checked where
it comes from a request, and the ``ondelete`` action is done where rows are
deleted.

The ``cortex_memory`` package declares its tables on its own base. They are
tenant tables (Appendix A); until the package has a tenant base of its own
(a change in ``hb-cortex-memory``, not in this repository's copy) the plane of
that base is assigned here.
"""
from __future__ import annotations

from typing import Any, NamedTuple, Optional

from sqlalchemy import MetaData, Table

from src.common.database import Base

CONTROL = "control"
TENANT = "tenant"
PLANES = (CONTROL, TENANT)

# The schema of a tenant database that holds the platform's own tables (TD-02).
TENANT_SCHEMA = "platform"


class _PlaneBase(Base):
    __abstract__ = True
    __plane__ = ""

    def __init_subclass__(cls, **kw: Any) -> None:
        super().__init_subclass__(**kw)  # maps the class
        table = cls.__dict__.get("__table__")
        if table is not None:
            table.info["plane"] = cls.__plane__


class ControlBase(_PlaneBase):
    """Tables of the control database (shared by every tenant)."""
    __abstract__ = True
    __plane__ = CONTROL


class TenantBase(_PlaneBase):
    """Tables of a tenant's database, schema ``platform``."""
    __abstract__ = True
    __plane__ = TENANT


def refers_to(target: str, *, ondelete: Optional[str] = None) -> dict[str, Any]:
    """``Column.info`` of a UUID column naming a row of the other plane (2.3).

    ``target`` is ``"table.column"``; ``ondelete`` is the action the dropped
    foreign key had (``"CASCADE"``, ``"SET NULL"``; ``None`` = refuse), which
    the code that deletes ``target`` rows now does itself.
    """
    return {"refers_to": target, "ondelete": ondelete}


class PlaneReference(NamedTuple):
    """A column that names a row of the other plane, without a foreign key."""
    table: str
    column: str
    referred_table: str
    referred_column: str
    ondelete: Optional[str]

    def __str__(self) -> str:
        return f"{self.table}.{self.column} -> {self.referred_table}"


# The ``cortex_memory`` package keeps its references to host rows opaque, with
# no keys (its decision K5), but the migration chain gave the shared database
# four to control tables, dropped with the others by 2.3.
_CORTEX_REFERENCES = (
    PlaneReference("cortex_trees", "app_id", "companies", "id", "SET NULL"),
    PlaneReference("cortex_trees", "company_id", "companies", "id", None),
    PlaneReference("cortex_trees", "partner_id", "companies", "id", "SET NULL"),
    PlaneReference("cortex_trees", "user_id", "users", "id", None),
)


def cortex_base() -> type:
    """The ``cortex_memory`` package's declarative base (its tables are tenant tables)."""
    import cortex_memory

    return cortex_memory.Base


def plane_bases() -> dict[str, tuple[type, ...]]:
    """The declarative bases of each plane: what a split-mode session binds."""
    return {CONTROL: (ControlBase,), TENANT: (TenantBase, cortex_base())}


def plane_of(table: Table) -> Optional[str]:
    """The table's plane, or ``None`` for a table no plane claims."""
    plane = table.info.get("plane")
    if plane:
        return str(plane)
    if table.metadata is cortex_base().metadata:
        return TENANT
    return None


def plane_tables(plane: str) -> list[Table]:
    """Every table of ``plane``, in dependency order (imports every model module)."""
    from src.common.orm_models import import_all_models

    return [table for metadata in import_all_models() for table in metadata.sorted_tables
            if plane_of(table) == plane]


def unclassified_tables() -> list[str]:
    """Tables no plane claims — there must be none."""
    from src.common.orm_models import import_all_models

    return sorted(table.name for metadata in import_all_models() for table in metadata.tables.values()
                  if plane_of(table) is None)


def cross_plane_foreign_keys() -> list[str]:
    """``table.column -> referred_table`` for every foreign key between the planes.

    There must be none: a tenant database cannot hold them (tech spec §5.3
    rule 2). Such a column is a plain UUID marked with ``refers_to()``.
    """
    from src.common.orm_models import import_all_models

    found = set()
    for metadata in import_all_models():
        for table in metadata.tables.values():
            for fk in table.foreign_keys:
                if plane_of(fk.column.table) != plane_of(table):
                    found.add(f"{table.name}.{fk.parent.name} -> {fk.column.table.name}")
    return sorted(found)


def cross_plane_references() -> list[PlaneReference]:
    """The CORTEX tables' references, then every column marked ``refers_to()``.

    What the foreign keys between the planes were (2.3): the test purge follows
    them, and ``tests/unit/test_tenancy.py`` pins them.
    """
    from src.common.orm_models import import_all_models

    found = list(_CORTEX_REFERENCES)
    for metadata in import_all_models():
        for table in metadata.sorted_tables:
            for column in table.columns:
                target = column.info.get("refers_to")
                if target:
                    referred_table, referred_column = target.rsplit(".", 1)
                    found.append(PlaneReference(table.name, column.name, referred_table, referred_column,
                                                column.info.get("ondelete")))
    return found


def cross_plane_relationships() -> list[str]:
    """``Class.attribute -> Target`` for every ORM relationship between the planes.

    There must be none: a joined load cannot cross two databases. Read the
    other plane's row by its id.
    """
    from src.common.orm_models import import_all_models

    import_all_models()
    found = set()
    for registry in (Base.registry, cortex_base().registry):
        for mapper in registry.mappers:
            for rel in mapper.relationships:
                source, target = mapper.persist_selectable, rel.mapper.persist_selectable
                if isinstance(source, Table) and isinstance(target, Table) \
                        and plane_of(source) != plane_of(target):
                    found.add(f"{mapper.class_.__name__}.{rel.key} -> {rel.mapper.class_.__name__}")
    return sorted(found)


def tenant_ddl_metadata(schema: str = TENANT_SCHEMA) -> MetaData:
    """The tenant tables as a tenant database holds them.

    Copies of the tenant tables in ``schema``, with their foreign keys (all
    between tenant tables). Before 2.7's tenant tree, tenant databases were
    built from this (``create_all``); the runner adopts such a database
    (``migrate.adopt``), and the tests build one to show it.
    """
    crossing = cross_plane_foreign_keys()
    if crossing:
        raise ValueError(f"a tenant database cannot hold foreign keys to control tables: {crossing}")
    target = MetaData(schema=schema)
    for table in plane_tables(TENANT):
        table.to_metadata(target, schema=schema)
    return target
