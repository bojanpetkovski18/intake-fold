from http import HTTPStatus

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

PROBLEM_MEDIA_TYPE = "application/problem+json"


def problem_body(status: int, detail: str, trace_id: str | None) -> dict[str, object]:
    return {
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "detail": detail,
        "traceId": trace_id,
    }


def problem_response(status: int, detail: str, **extra: object) -> JSONResponse:
    trace_id = structlog.contextvars.get_contextvars().get("trace_id")
    return JSONResponse(
        problem_body(status, detail, trace_id) | extra,
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
    )


def _http_exception(_: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, HTTPException)  # noqa: S101 - narrows the type Starlette registers
    response = problem_response(error.status_code, str(error.detail))
    response.headers.update(error.headers or {})
    return response


def _validation_error(_: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, RequestValidationError)  # noqa: S101 - narrows the registered type
    # Only location and message: the rejected input may be sensitive.
    errors = [
        {"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
        for item in error.errors()
    ]
    return problem_response(422, "The request is not valid.", errors=errors)


def register_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, _http_exception)
    app.add_exception_handler(RequestValidationError, _validation_error)
