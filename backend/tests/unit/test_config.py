from pathlib import Path

import pytest
from pydantic import ValidationError

from energy_forecast.config import Environment, Service, Settings

_SETTING_NAMES = (
    "APP_ENV",
    "APP_SERVICE",
    "APP_HOST",
    "APP_PORT",
    "DATABASE_URL",
    "ARTIFACT_ROOT",
    "CORS_ORIGINS",
    "MAX_UPLOAD_BYTES",
    "LOG_LEVEL",
    "CODE_COMMIT",
    "WORKER_POLL_INTERVAL_SECONDS",
    "WORKER_HEARTBEAT_INTERVAL_SECONDS",
    "WORKER_STALE_AFTER_SECONDS",
    "WORKER_RECOVERY_BATCH_SIZE",
    "WORKER_RUN_ONCE",
)


@pytest.fixture(autouse=True)
def clean_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _SETTING_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_settings_load_and_coerce_environment_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_SERVICE", "worker")
    monkeypatch.setenv("APP_PORT", "9001")
    monkeypatch.setenv("ARTIFACT_ROOT", "runtime/artifacts")
    monkeypatch.setenv("CORS_ORIGINS", "https://one.example, https://two.example")
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "1024")
    monkeypatch.setenv("LOG_LEVEL", "debug")

    settings = Settings()

    assert settings.environment is Environment.TEST
    assert settings.service is Service.WORKER
    assert settings.app_port == 9001
    assert settings.artifact_root == Path("runtime/artifacts")
    assert settings.cors_origins == ("https://one.example", "https://two.example")
    assert settings.max_upload_bytes == 1024
    assert settings.log_level == "DEBUG"


def test_missing_required_production_configuration_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")

    with pytest.raises(ValidationError) as error:
        Settings()

    message = str(error.value)
    assert "DATABASE_URL" in message
    assert "CODE_COMMIT" in message


def test_complete_production_configuration_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://energyforecast:secret@db:5432/energyforecast",
    )
    monkeypatch.setenv("CODE_COMMIT", "abc1234")

    settings = Settings()

    assert settings.environment is Environment.PRODUCTION
    assert settings.database_url is not None
    assert settings.database_url.get_secret_value().endswith("/energyforecast")
    assert settings.code_commit == "abc1234"


def test_invalid_typed_setting_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PORT", "70000")

    with pytest.raises(ValidationError):
        Settings()


def test_stale_timeout_must_exceed_heartbeat_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKER_HEARTBEAT_INTERVAL_SECONDS", "10")
    monkeypatch.setenv("WORKER_STALE_AFTER_SECONDS", "10")

    with pytest.raises(ValidationError, match="must be less"):
        Settings()


def test_invalid_database_scheme_is_rejected_without_echoing_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_url = "postgresql://energyforecast:do-not-echo@db:5432/energyforecast"
    monkeypatch.setenv("DATABASE_URL", invalid_url)

    with pytest.raises(ValidationError) as error:
        Settings()

    assert "postgresql+asyncpg" in str(error.value)
    assert "do-not-echo" not in str(error.value)
