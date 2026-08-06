"""Alembic environment for async PostgreSQL migrations."""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from energy_forecast.database import models as database_models  # noqa: F401
from energy_forecast.database.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def configured_database_url() -> str:
    """Prefer an explicit runtime URL and retain a reproducible local fallback."""
    explicit_url = config.attributes.get("database_url")
    if isinstance(explicit_url, str):
        return explicit_url
    return os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url"))


def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
    """Restrict drift checks to the three application-owned schemas."""
    if type_ == "schema":
        return name in {"app", "ts", "ml"}
    schema_name = parent_names.get("schema_name")
    return schema_name in {None, "app", "ts", "ml"}


def include_object(
    object_: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object | None,
) -> bool:
    """Avoid false drift from PostgreSQL-assigned names on equivalent check constraints."""
    del object_, name, reflected, compare_to
    return type_ != "check_constraint"


def configure_context(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=configured_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = configured_database_url()
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(configure_context)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
