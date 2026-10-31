import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from intakefold.api.access import enforce_access
from intakefold.api.app import build_app
from intakefold.settings import Settings

UNREACHABLE = "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none"


def make_app(environment: str = "test") -> FastAPI:
    settings = Settings.model_validate({"database_url": UNREACHABLE, "environment": environment})
    app = build_app(settings)
    # These tests are about error shape and headers; the access rules have their own tests.
    app.dependency_overrides[enforce_access] = lambda: None

    @app.get("/api/explode")
    def explode() -> None:
        raise RuntimeError("private detail")

    @app.get("/api/numbers/{number}")
    def number(number: int) -> dict[str, int]:
        return {"number": number}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(make_app(), raise_server_exceptions=False)


def assert_problem(response_json: dict[str, object], status: int, trace_header: str) -> None:
    assert response_json["status"] == status
    assert response_json["type"] == "about:blank"
    assert response_json["title"]
    assert response_json["detail"]
    assert response_json["traceId"] == trace_header
    assert uuid.UUID(trace_header).hex == trace_header


def assert_security_headers(headers: dict[str, str]) -> None:
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert "camera=()" in headers["permissions-policy"]


def test_not_found_is_a_problem_with_headers_and_trace_id(client: TestClient) -> None:
    response = client.get("/api/missing")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert_problem(response.json(), 404, response.headers["x-trace-id"])
    assert_security_headers(dict(response.headers))


def test_unexpected_error_has_headers_trace_id_and_no_detail(client: TestClient) -> None:
    response = client.get("/api/explode")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert_problem(response.json(), 500, response.headers["x-trace-id"])
    assert_security_headers(dict(response.headers))
    assert "private detail" not in response.text


def test_validation_error_omits_the_rejected_input(client: TestClient) -> None:
    response = client.get("/api/numbers/not-a-number-secret")

    assert response.status_code == 422
    assert_problem(response.json(), 422, response.headers["x-trace-id"])
    assert response.json()["errors"][0]["field"] == "path.number"
    assert "not-a-number-secret" not in response.text


def test_each_request_gets_its_own_trace_id(client: TestClient) -> None:
    first = client.get("/api/missing").headers["x-trace-id"]
    second = client.get("/api/missing").headers["x-trace-id"]

    assert first != second


def test_client_cannot_set_the_trace_id(client: TestClient) -> None:
    response = client.get("/api/missing", headers={"X-Trace-Id": "injected"})

    assert response.headers["x-trace-id"] != "injected"


@pytest.mark.parametrize(("environment", "expected"), [("production", True), ("test", False)])
def test_hsts_only_in_production(environment: str, expected: bool) -> None:
    response = TestClient(make_app(environment)).get("/api/missing")

    assert ("strict-transport-security" in response.headers) is expected


def test_request_log_is_json_with_trace_id_and_no_query_string(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    response = client.get("/api/missing?token=hunter2")

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    finished = next(line for line in lines if line["event"] == "request_finished")
    assert finished["trace_id"] == response.headers["x-trace-id"]
    assert finished["status"] == 404
    assert "hunter2" not in json.dumps(lines)
