import pytest
from fastapi.testclient import TestClient

from intakefold.api.app import build_app
from intakefold.settings import Settings

pytestmark = pytest.mark.integration


def client_for(database_url: str) -> TestClient:
    return TestClient(build_app(Settings.model_validate({"database_url": database_url})))


def test_health_reports_ok_with_a_real_database(database_url: str) -> None:
    # The context manager runs the lifespan, so the engine is disposed.
    with client_for(database_url) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-trace-id"]


def test_health_is_503_without_leaking_the_url_when_the_database_is_down() -> None:
    url = "postgresql+psycopg://nobody:hunter2@127.0.0.1:1/none"

    response = client_for(url).get("/api/health")

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert "hunter2" not in response.text
