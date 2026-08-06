from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from energy_forecast.api import create_app
from energy_forecast.config import Environment, Service, Settings
from energy_forecast.errors import ApiProblem


class PassingReadinessCheck:
    def __init__(self) -> None:
        self.calls = 0

    async def check(self) -> None:
        self.calls += 1


class FailingReadinessCheck:
    def __init__(self) -> None:
        self.calls = 0

    async def check(self) -> None:
        self.calls += 1
        raise RuntimeError("database password and host must not reach the client")


def _settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        service=Service.API,
        code_commit="test-commit",
        log_level="INFO",
    )


def _client(
    readiness_check: PassingReadinessCheck | FailingReadinessCheck,
) -> tuple[FastAPI, TestClient]:
    app = create_app(_settings(), readiness_check)
    return app, TestClient(app, raise_server_exceptions=False)


def test_liveness_does_not_call_database_dependency() -> None:
    check = FailingReadinessCheck()
    _, client = _client(check)

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"process": "ok"}}
    assert check.calls == 0
    UUID(response.headers["X-Request-ID"])


def test_readiness_is_ok_when_database_dependency_is_available() -> None:
    check = PassingReadinessCheck()
    _, client = _client(check)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok"}}
    assert check.calls == 1


def test_readiness_returns_problem_when_database_dependency_is_unavailable() -> None:
    check = FailingReadinessCheck()
    _, client = _client(check)

    response = client.get("/health/ready", headers={"X-Request-ID": "ready-request"})

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["X-Request-ID"] == "ready-request"
    assert response.json() == {
        "type": "/problems/database_unavailable",
        "title": "Сервіс не готовий",
        "status": 503,
        "detail": "Немає з’єднання з обов’язковою базою даних.",
        "instance": "/health/ready",
        "code": "database_unavailable",
        "request_id": "ready-request",
    }
    assert "password" not in response.text
    assert check.calls == 1


def test_request_id_is_preserved_in_response_and_structured_log(capsys: Any) -> None:
    _, client = _client(PassingReadinessCheck())

    response = client.get("/health/live", headers={"X-Request-ID": "client-request-42"})

    assert response.headers["X-Request-ID"] == "client-request-42"
    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    request_record = next(
        record for record in records if record["event"] == "http_request_completed"
    )
    assert request_record["request_id"] == "client-request-42"
    assert request_record["path"] == "/health/live"
    assert request_record["status_code"] == 200
    assert isinstance(request_record["duration_ms"], float)


def test_invalid_request_id_is_replaced() -> None:
    _, client = _client(PassingReadinessCheck())

    response = client.get("/health/live", headers={"X-Request-ID": "invalid id with spaces"})

    generated = response.headers["X-Request-ID"]
    assert generated != "invalid id with spaces"
    UUID(generated)


def test_expected_api_error_uses_problem_details() -> None:
    app, client = _client(PassingReadinessCheck())

    @app.get("/test/conflict")
    async def conflict() -> None:
        raise ApiProblem(
            status=409,
            code="test_conflict",
            title="Конфлікт",
            detail="Тестовий ресурс конфліктує.",
        )

    response = client.get("/test/conflict", headers={"X-Request-ID": "conflict-request"})

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "test_conflict"
    assert response.json()["request_id"] == "conflict-request"


def test_unexpected_error_is_logged_but_not_leaked_to_client(capsys: Any) -> None:
    app, client = _client(PassingReadinessCheck())

    @app.get("/test/crash")
    async def crash() -> None:
        raise RuntimeError("secret traceback marker")

    response = client.get("/test/crash", headers={"X-Request-ID": "crash-request"})

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["X-Request-ID"] == "crash-request"
    assert response.json()["code"] == "internal_error"
    assert response.json()["request_id"] == "crash-request"
    assert "secret traceback marker" not in response.text
    assert "Traceback" not in response.text
    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    failure_record = next(record for record in records if record["event"] == "http_request_failed")
    assert failure_record["request_id"] == "crash-request"
    assert failure_record["error_code"] == "internal_error"
    assert "secret traceback marker" in failure_record["exception"]


def test_validation_error_is_ukrainian_problem_details() -> None:
    app, client = _client(PassingReadinessCheck())

    @app.get("/test/validated")
    async def validated(limit: int) -> dict[str, int]:
        return {"limit": limit}

    response = client.get("/test/validated", params={"limit": "not-an-integer"})

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["title"] == "Помилка перевірки даних"
    assert response.json()["code"] == "validation_error"


def test_runtime_openapi_documents_health_and_problem_details() -> None:
    app, _ = _client(PassingReadinessCheck())

    schema = app.openapi()

    assert schema["paths"]["/health/live"]["get"]["operationId"] == "getLiveness"
    readiness = schema["paths"]["/health/ready"]["get"]
    assert readiness["operationId"] == "getReadiness"
    assert "503" in readiness["responses"]
    assert readiness["responses"]["503"]["content"] == {
        "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
    }
    assert "Problem" in schema["components"]["schemas"]
