"""RFC-style Problem Details responses for API failures."""

from __future__ import annotations

from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_MEDIA_TYPE = "application/problem+json"
REQUEST_ID_HEADER = "X-Request-ID"


class Problem(BaseModel):
    """Portable API error representation based on RFC 9457."""

    model_config = ConfigDict(json_schema_extra={"description": "RFC 9457 Problem Details"})

    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    code: str
    request_id: str


class ApiProblem(Exception):
    """Expected API failure safe to return to a client."""

    def __init__(self, *, status: int, code: str, title: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def _problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
) -> JSONResponse:
    request_id = _request_id(request)
    problem = Problem(
        type=f"/problems/{code}",
        title=title,
        status=status,
        detail=detail,
        instance=request.url.path,
        code=code,
        request_id=request_id,
    )
    return JSONResponse(
        status_code=status,
        content=problem.model_dump(exclude_none=True),
        media_type=PROBLEM_MEDIA_TYPE,
        headers={REQUEST_ID_HEADER: request_id},
    )


async def api_problem_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiProblem):
        raise TypeError("api_problem_handler requires ApiProblem")
    return _problem_response(
        request,
        status=exc.status,
        code=exc.code,
        title=exc.title,
        detail=exc.detail,
    )


async def validation_problem_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise TypeError("validation_problem_handler requires RequestValidationError")
    return _problem_response(
        request,
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
        code="validation_error",
        title="Помилка перевірки даних",
        detail="Надіслані дані не пройшли перевірку.",
    )


async def http_problem_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        raise TypeError("http_problem_handler requires HTTPException")
    title, detail, code = _http_problem_text(exc.status_code)
    return _problem_response(
        request,
        status=exc.status_code,
        code=code,
        title=title,
        detail=detail,
    )


async def unexpected_problem_handler(request: Request, exc: Exception) -> JSONResponse:
    return _problem_response(
        request,
        status=HTTPStatus.INTERNAL_SERVER_ERROR,
        code="internal_error",
        title="Внутрішня помилка сервера",
        detail="Сталася неочікувана помилка. Повторіть спробу пізніше.",
    )


def _http_problem_text(status: int) -> tuple[str, str, str]:
    if status == HTTPStatus.NOT_FOUND:
        return "Ресурс не знайдено", "Запитаний ресурс не знайдено.", "not_found"
    if status == HTTPStatus.METHOD_NOT_ALLOWED:
        return "Метод не дозволено", "Цей HTTP-метод не підтримується.", "method_not_allowed"
    return "Помилка HTTP-запиту", "Не вдалося виконати HTTP-запит.", f"http_{status}"


def install_exception_handlers(app: FastAPI) -> None:
    """Install one Problem Details boundary for expected and unexpected failures."""
    app.add_exception_handler(ApiProblem, api_problem_handler)
    app.add_exception_handler(RequestValidationError, validation_problem_handler)
    app.add_exception_handler(StarletteHTTPException, http_problem_handler)
    app.add_exception_handler(Exception, unexpected_problem_handler)
