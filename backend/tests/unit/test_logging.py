import json
import logging
from typing import Any

from energy_forecast.config import Environment, Service, Settings
from energy_forecast.logging_config import bind_request_id, configure_logging, reset_request_id


def test_json_log_contains_required_context(capsys: Any) -> None:
    settings = Settings(
        environment=Environment.TEST,
        service=Service.WORKER,
        code_commit="test-commit",
    )
    configure_logging(settings)
    token = bind_request_id("request-123")
    try:
        logging.getLogger("test").info(
            "job_progress",
            extra={"event": "job_progress", "job_id": "job-456", "duration_ms": 12.5},
        )
    finally:
        reset_request_id(token)

    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert payload["level"] == "INFO"
    assert payload["service"] == "worker"
    assert payload["environment"] == "test"
    assert payload["code_commit"] == "test-commit"
    assert payload["event"] == "job_progress"
    assert payload["request_id"] == "request-123"
    assert payload["job_id"] == "job-456"
    assert payload["duration_ms"] == 12.5
    assert payload["error_code"] is None


def test_configure_logging_reenables_package_loggers() -> None:
    package_logger = logging.getLogger("energy_forecast.test.disabled")
    package_logger.disabled = True
    package_logger.addHandler(logging.NullHandler())

    configure_logging(Settings(environment=Environment.TEST, service=Service.API))

    assert package_logger.disabled is False
    assert package_logger.handlers == []
    assert package_logger.propagate is True
