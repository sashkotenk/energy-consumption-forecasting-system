from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL, make_url

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = "TEST_DATABASE_URL"


def _render_url(url: URL) -> str:
    return url.render_as_string(hide_password=False)


def _asyncpg_url(url: URL) -> str:
    return _render_url(url.set(drivername="postgresql"))


async def _create_database(admin_url: URL, database_name: str) -> None:
    connection = await asyncpg.connect(_asyncpg_url(admin_url))
    try:
        await connection.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        await connection.close()


async def _drop_database(admin_url: URL, database_name: str) -> None:
    connection = await asyncpg.connect(_asyncpg_url(admin_url))
    try:
        await connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
    finally:
        await connection.close()


@pytest.fixture
def temporary_database_url() -> Iterator[str]:
    raw_url = os.environ.get(TEST_DATABASE_URL)
    if raw_url is None:
        pytest.skip(f"{TEST_DATABASE_URL} is required for TimescaleDB integration tests")

    server_url = make_url(raw_url)
    if server_url.drivername != "postgresql+asyncpg":
        pytest.fail(f"{TEST_DATABASE_URL} must use postgresql+asyncpg")

    database_name = f"energyforecast_test_{uuid4().hex}"
    admin_url = server_url.set(database="postgres")
    test_url = server_url.set(database=database_name)
    asyncio.run(_create_database(admin_url, database_name))
    try:
        yield _render_url(test_url)
    finally:
        asyncio.run(_drop_database(admin_url, database_name))


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade_database(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")
