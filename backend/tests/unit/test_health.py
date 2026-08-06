import asyncio

import pytest

from energy_forecast.health import MissingDatabaseReadinessCheck


def test_missing_database_readiness_check_fails() -> None:
    check = MissingDatabaseReadinessCheck()

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        asyncio.run(check.check())
