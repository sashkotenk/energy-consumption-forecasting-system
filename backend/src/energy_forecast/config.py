"""Typed application configuration loaded from environment variables."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    """Supported deployment environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Service(StrEnum):
    """Runnable processes in the modular monolith."""

    API = "api"
    WORKER = "worker"


LogLevel = Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]


class Settings(BaseSettings):
    """Validated process settings with safe local-development defaults."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    environment: Environment = Field(
        default=Environment.DEVELOPMENT,
        validation_alias="APP_ENV",
    )
    service: Service = Field(default=Service.API, validation_alias="APP_SERVICE")
    app_host: str = Field(default="0.0.0.0", min_length=1, validation_alias="APP_HOST")
    app_port: int = Field(default=8000, ge=1, le=65535, validation_alias="APP_PORT")
    database_url: SecretStr | None = Field(default=None, validation_alias="DATABASE_URL")
    artifact_root: Path = Field(
        default=Path("artifacts"),
        validation_alias="ARTIFACT_ROOT",
    )
    cors_origins: Annotated[tuple[str, ...], NoDecode] = Field(
        default=("http://localhost:5173",),
        validation_alias="CORS_ORIGINS",
    )
    max_upload_bytes: int = Field(
        default=314_572_800,
        gt=0,
        validation_alias="MAX_UPLOAD_BYTES",
    )
    log_level: LogLevel = Field(default="INFO", validation_alias="LOG_LEVEL")
    code_commit: str = Field(default="unknown", min_length=1, validation_alias="CODE_COMMIT")
    worker_poll_interval_seconds: float = Field(
        default=1.0,
        ge=0.05,
        le=60,
        validation_alias="WORKER_POLL_INTERVAL_SECONDS",
    )
    worker_heartbeat_interval_seconds: float = Field(
        default=5.0,
        ge=0.05,
        le=300,
        validation_alias="WORKER_HEARTBEAT_INTERVAL_SECONDS",
    )
    worker_stale_after_seconds: float = Field(
        default=30.0,
        ge=0.1,
        le=3600,
        validation_alias="WORKER_STALE_AFTER_SECONDS",
    )
    worker_recovery_batch_size: int = Field(
        default=100,
        ge=1,
        le=1000,
        validation_alias="WORKER_RECOVERY_BATCH_SIZE",
    )
    worker_run_once: bool = Field(default=False, validation_alias="WORKER_RUN_ONCE")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        """Accept a comma-separated environment value while retaining tuple typing."""
        if isinstance(value, str):
            return tuple(origin.strip() for origin in value.split(",") if origin.strip())
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            return value.upper()
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return value
        raw_value = value.get_secret_value()
        if not raw_value.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg scheme")
        return value

    @model_validator(mode="after")
    def validate_production_requirements(self) -> Self:
        if self.worker_heartbeat_interval_seconds >= self.worker_stale_after_seconds:
            raise ValueError(
                "WORKER_HEARTBEAT_INTERVAL_SECONDS must be less than WORKER_STALE_AFTER_SECONDS"
            )
        if self.environment is not Environment.PRODUCTION:
            return self

        missing: list[str] = []
        if self.database_url is None:
            missing.append("DATABASE_URL")
        if self.code_commit == "unknown":
            missing.append("CODE_COMMIT")
        if missing:
            names = ", ".join(missing)
            raise ValueError(f"Missing required production configuration: {names}")
        return self
