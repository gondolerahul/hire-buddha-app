"""What the two migration trees' ``env.py`` files share (Phase 14 WS2 2.7, tech spec §5.4).

One Alembic tree per plane (``src.common.tenancy.bases``):

* ``migrations/control`` (``alembic.ini`` section ``[alembic]``) — the control
  tables, in the control database (in ``TENANCY_MODE=single``, the shared
  database). Version table ``alembic_version``.
* ``migrations/tenant_platform`` (section ``[tenant_platform]``) — a tenant's
  tables: schema ``platform`` of each tenant database, or ``public`` of the
  shared database in single mode. Version table ``alembic_version_tenant_platform``
  in that schema. Its revisions name tables unqualified; the connection's
  ``search_path`` puts the target schema first.

Each tree compares only its own plane's tables, so in the shared database
neither sees the other's as tables to drop. Normally ``python -m
src.common.tenancy.migrate`` runs them; Alembic's own commands work too::

    alembic upgrade head                                            # control
    alembic -n tenant_platform -x database=t_devacme01 upgrade head
    alembic -n tenant_platform -x schema=public upgrade head        # single mode
    alembic -n tenant_platform -x database=t_devacme01 check

``-x database=`` / ``host=`` / ``port=`` change the control URL's database and
server; the runner hands a tenant database's whole URL over in
``HB_MIGRATION_URL`` instead. The models are imported (slow: the whole app)
only for ``check`` and ``revision --autogenerate``.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

from alembic import context

from src.common.tenancy.migrate import (  # noqa: F401  (CONTROL_TREE, TENANT_TREE: what env.py passes)
    CONTROL_TREE, TENANT_SCHEMA, TENANT_TREE, TENANT_VERSION_TABLE, URL_VARIABLE,
)

# What a database the old chain built has on the CORTEX tables and the
# ``cortex_memory`` package's models do not declare: the package keeps its
# references to host rows opaque (its decision K5) and leaves indexes and NOT
# NULL to the host, whose chain added them. The baseline creates them; the
# comparison leaves them alone. Carry them into the package (hb-cortex-memory)
# to empty these sets.
CORTEX_DB_ONLY_INDEXES = frozenset({
    "ix_cortex_nodes_created_at", "ix_cortex_nodes_embedding", "ix_cortex_nodes_importance",
    "ix_cortex_trees_next_resume", "ix_cortex_trees_scope_entity", "ix_cortex_trees_scope_user",
})
CORTEX_DB_ONLY_FOREIGN_KEYS = frozenset({
    "cortex_nodes_execution_run_id_fkey", "cortex_trees_entity_id_fkey", "fk_cortex_trees_run_id",
    "fk_cortex_trees_root_node", "fk_cortex_trees_output_root", "fk_cortex_trees_resume_cursor",
})
CORTEX_DB_ONLY_NOT_NULL = frozenset({
    ("cortex_nodes", "access_count"), ("cortex_nodes", "importance_score"),
    ("cortex_trees", "is_persistent"), ("cortex_trees", "consolidation_generation"),
})


def plane_metadata(tree: str) -> Any:
    """The tree's tables, unqualified (the models: imports every model module)."""
    from sqlalchemy import MetaData

    from src.common.tenancy.bases import CONTROL, TENANT, plane_tables

    target = MetaData()
    for table in plane_tables(CONTROL if tree == CONTROL_TREE else TENANT):
        table.to_metadata(target, schema=None)
    return target


def comparison_options(tree: str, metadata: Any) -> dict[str, Any]:
    """``context.configure`` options that keep a comparison to ``metadata``'s tables (and the allow-lists)."""
    names = frozenset(metadata.tables)

    def include_name(name: Optional[str], type_: str, parent_names: dict) -> bool:
        return name in names if type_ == "table" else True

    def include_object(obj: Any, name: Optional[str], type_: str, reflected: bool, compare_to: Any) -> bool:
        if tree != TENANT_TREE or not reflected or compare_to is not None:
            return True
        if type_ == "index":
            return name not in CORTEX_DB_ONLY_INDEXES
        if type_ == "foreign_key_constraint":
            return name not in CORTEX_DB_ONLY_FOREIGN_KEYS
        return True

    def process_revision_directives(ctx: Any, revision: Any, directives: list) -> None:
        if tree != TENANT_TREE:
            return
        from alembic.operations import ops

        for script in directives:
            for upgrade_ops in script.upgrade_ops_list:
                kept = []
                for op in upgrade_ops.ops:
                    if isinstance(op, ops.ModifyTableOps):
                        op.ops = [o for o in op.ops if not _allowed_nullability(op.table_name, o)]
                        if not op.ops:
                            continue
                    kept.append(op)
                upgrade_ops.ops = kept

    return {"include_name": include_name, "include_object": include_object,
            "process_revision_directives": process_revision_directives, "compare_type": True}


def _allowed_nullability(table: str, op: Any) -> bool:
    from alembic.operations import ops

    return (isinstance(op, ops.AlterColumnOp) and (table, op.column_name) in CORTEX_DB_ONLY_NOT_NULL
            and op.modify_nullable is True and op.modify_type is None and op.modify_server_default is False
            and op.modify_name is None and op.modify_comment is False)


def _comparing(config: Any) -> bool:
    if "compare" in config.attributes:
        return bool(config.attributes["compare"])
    cmd = getattr(config.cmd_opts, "cmd", None)
    name = getattr(cmd[0], "__name__", "") if cmd else ""
    return name == "check" or (name == "revision" and bool(getattr(config.cmd_opts, "autogenerate", False)))


def _target(config: Any, tree: str) -> tuple[Any, Optional[str]]:
    """(URL, schema): the database the tree runs on and, for the tenant tree, its schema."""
    from sqlalchemy.engine import make_url

    from src.common.config import settings

    x = context.get_x_argument(as_dictionary=True)
    control = make_url(settings.CONTROL_DATABASE_URL)
    url = make_url(config.attributes.get("url") or os.environ.get(URL_VARIABLE) or control)
    if x.get("host"):
        url = url.set(host=x["host"])
    if x.get("port"):
        url = url.set(port=int(x["port"]))
    if x.get("database"):
        url = url.set(database=x["database"])
    if tree == CONTROL_TREE:  # a schema of its own only for the runner's scratch copy (``migrate.cross_the_cut``)
        return url, config.attributes.get("schema")
    schema = config.attributes.get("schema") or x.get("schema") or TENANT_SCHEMA
    if schema == TENANT_SCHEMA and (url.host, url.port, url.database) == (control.host, control.port, control.database):
        raise SystemExit("the tenant tree on the control database: its tenant tables are in public "
                         "(-x schema=public, TENANCY_MODE=single), or name a tenant database (-x database=t_<key>)")
    return url, schema


def _configure_and_run(connection: Any, tree: str, schema: Optional[str], metadata: Any,
                       create_schema: bool = True) -> None:
    if create_schema and schema and schema != "public":
        connection.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        connection.commit()
    options: dict[str, Any] = comparison_options(tree, metadata) if metadata is not None else {}
    if tree == TENANT_TREE:
        options.update(version_table=TENANT_VERSION_TABLE)
    if schema:
        options.update(version_table_schema=schema)
    context.configure(connection=connection, target_metadata=metadata, **options)
    with context.begin_transaction():
        context.run_migrations()


def run_env(tree: str) -> None:
    """The body of ``migrations/<tree>/env.py``."""
    from logging.config import fileConfig

    config = context.config
    if config.config_file_name is not None and not config.attributes.get("skip_logging"):
        fileConfig(config.config_file_name, disable_existing_loggers=False)
    metadata = plane_metadata(tree) if _comparing(config) else None

    given = config.attributes.get("connection")
    if given is not None:  # a caller's connection: its search_path set, its transaction the caller's
        schema = (config.attributes.get("schema") or TENANT_SCHEMA) if tree == TENANT_TREE \
            else config.attributes.get("schema")
        _configure_and_run(given, tree, schema, metadata, create_schema=False)
        return

    url, schema = _target(config, tree)
    if context.is_offline_mode():
        options = {"version_table": TENANT_VERSION_TABLE} if tree == TENANT_TREE else {}
        if schema:
            options["version_table_schema"] = schema
        context.configure(url=url.render_as_string(hide_password=True), target_metadata=metadata,
                          literal_binds=True, dialect_opts={"paramstyle": "named"}, **options)
        with context.begin_transaction():
            if schema:
                context.execute(f"SET search_path TO {_search_path(schema)}")
            context.run_migrations()
        return
    asyncio.run(_run_online(url, tree, schema, metadata))


def _search_path(schema: str) -> str:
    return "public" if schema == "public" else f'"{schema}", public'  # public: the extensions (vector)


async def _run_online(url: Any, tree: str, schema: Optional[str], metadata: Any) -> None:
    from sqlalchemy import pool
    from sqlalchemy.ext.asyncio import create_async_engine

    from src.common.platform.dbauth import install as install_db_auth

    connect_args = {"server_settings": {"search_path": _search_path(schema)}} if schema else {}
    engine = create_async_engine(url, poolclass=pool.NullPool, connect_args=connect_args)
    # On Azure the migrator signs in with its Entra identity (DB_AUTH, Phase 14).
    install_db_auth(engine)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_configure_and_run, tree, schema, metadata)
    finally:
        await engine.dispose()
