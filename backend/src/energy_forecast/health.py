"""Health endpoints and dependency readiness abstractions."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Literal, Protocol

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from energy_forecast.errors import PROBLEM_MEDIA_TYPE, ApiProblem, Problem


class ReadinessCheck(Protocol):
    """Port for a required API dependency health check."""

    async def check(self) -> None:
        """Return normally when ready or raise when unavailable."""
        ...


class DatabaseReadinessCheck:
    """Check the configured PostgreSQL dependency without exposing its URL."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    async def check(self) -> None:
        engine = create_async_engine(self._database_url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        finally:
            await engine.dispose()


class MissingDatabaseReadinessCheck:
    """Report a deliberately unconfigured development database as not ready."""

    async def check(self) -> None:
        raise RuntimeError("DATABASE_URL is not configured")


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, str]


def create_health_router(readiness_check: ReadinessCheck) -> APIRouter:
    router = APIRouter(prefix="/health", tags=["System"])

    @router.get(
        "/live",
        operation_id="getLiveness",
        response_model=HealthResponse,
        summary="Process liveness",
    )
    async def get_liveness() -> HealthResponse:
        return HealthResponse(status="ok", checks={"process": "ok"})

    @router.get(
        "/ready",
        operation_id="getReadiness",
        response_model=HealthResponse,
        responses={
            HTTPStatus.SERVICE_UNAVAILABLE: {
                "model": Problem,
                "description": "Required database dependency is unavailable",
                "content": {PROBLEM_MEDIA_TYPE: {}},
            }
        },
        summary="Dependency readiness",
    )
    async def get_readiness() -> HealthResponse:
        try:
            await readiness_check.check()
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "readiness_check_failed",
                extra={"event": "readiness_check_failed", "error_code": "database_unavailable"},
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            raise ApiProblem(
                status=HTTPStatus.SERVICE_UNAVAILABLE,
                code="database_unavailable",
                title="Сервіс не готовий",
                detail="Немає з’єднання з обов’язковою базою даних.",
            ) from exc
        return HealthResponse(status="ok", checks={"database": "ok"})

    return router
