"""The old single chain (``alembic -n legacy``), frozen (Phase 14 WS2 2.7).

Squashed into ``control/`` and ``tenant_platform/`` at ``p14_run_settlement``.
``python -m src.common.tenancy.migrate control`` runs it to bring a database
still on it (production's, on ``main``'s chain) up to that revision before
stamping the baselines. Nothing new goes in ``versions/``; the directory goes
once production has crossed.
"""
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from src.common.config import settings

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None and not config.attributes.get("skip_logging"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Frozen: no autogenerate, so no models (they now describe the two trees).
target_metadata = None

# The runner's URL (``config.attributes["url"]``), else the one from settings.
config.set_main_option("sqlalchemy.url",
                       (config.attributes.get("url") or settings.CONTROL_DATABASE_URL).replace("%", "%%"))


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    # On Azure the migrator signs in with its Entra identity (DB_AUTH, Phase 14).
    from src.common.platform.dbauth import install as install_db_auth

    install_db_auth(connectable)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
