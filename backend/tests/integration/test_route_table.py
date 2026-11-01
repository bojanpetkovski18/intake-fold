from collections.abc import Iterator
from typing import Annotated

import pytest
from conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    ORIGIN,
    REVIEWER_EMAIL,
    REVIEWER_PASSWORD,
    BuildApp,
    https_client,
    sign_in,
)
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from intakefold.api.access import PUBLIC_ROUTES, require_role
from intakefold.db.models import Role
from intakefold.identity.sessions import Principal

pytestmark = pytest.mark.integration

PUBLIC = "public"
SIGNED_IN = "signed in"

# Every route, and who may call it. Each milestone adds its routes here, or the first test fails.
ROUTE_TABLE: dict[tuple[str, str], str | Role] = {
    ("GET", "/api/health"): PUBLIC,
    ("POST", "/api/auth/login"): PUBLIC,
    ("POST", "/api/auth/logout"): SIGNED_IN,
    ("GET", "/api/auth/me"): SIGNED_IN,
    ("POST", "/api/documents"): Role.REVIEWER,
    ("GET", "/api/documents"): Role.REVIEWER,
    ("GET", "/api/documents/{document_id}"): Role.REVIEWER,
    ("GET", "/api/documents/{document_id}/pages/{page}"): Role.REVIEWER,
}
PATH_VALUES = {"document_id": "00000000-0000-7000-8000-000000000000", "page": 1}
PROTECTED = [
    (method, path.format(**PATH_VALUES))
    for (method, path), access in ROUTE_TABLE.items()
    if access != PUBLIC
]
UNSAFE_PROTECTED = [route for route in PROTECTED if route[0] != "GET"]


@pytest.fixture
def anonymous(seeded: Engine, build: BuildApp) -> Iterator[TestClient]:
    with https_client(build()) as client:
        yield client


def test_route_table_lists_every_route(build: BuildApp) -> None:
    # The schema, not app.routes: FastAPI keeps included routers as private wrapper objects.
    paths: dict[str, dict[str, object]] = build().openapi()["paths"]
    routes = {(method.upper(), path) for path, item in paths.items() for method in item}

    assert routes == set(ROUTE_TABLE)


def test_public_routes_match_the_table() -> None:
    assert {route for route, access in ROUTE_TABLE.items() if access == PUBLIC} == PUBLIC_ROUTES


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_anonymous_call_is_refused(anonymous: TestClient, method: str, path: str) -> None:
    response = anonymous.request(method, path, headers={"Origin": ORIGIN})

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_made_up_session_is_refused(anonymous: TestClient, method: str, path: str) -> None:
    response = anonymous.request(
        method,
        path,
        headers={"Origin": ORIGIN, "Cookie": "intakefold_session=made-up"},
    )

    assert response.status_code == 401


@pytest.mark.parametrize(("method", "path"), UNSAFE_PROTECTED)
def test_missing_csrf_token_is_refused(anonymous: TestClient, method: str, path: str) -> None:
    sign_in(anonymous, REVIEWER_EMAIL, REVIEWER_PASSWORD)

    response = anonymous.request(method, path, headers={"Origin": ORIGIN})

    assert response.status_code == 403


@pytest.mark.parametrize(("method", "path"), UNSAFE_PROTECTED)
def test_valid_csrf_token_from_a_bad_origin_is_refused(
    anonymous: TestClient, method: str, path: str
) -> None:
    csrf_token = sign_in(anonymous, REVIEWER_EMAIL, REVIEWER_PASSWORD)

    response = anonymous.request(
        method,
        path,
        headers={"Origin": "https://evil.example.com", "X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 403


def test_a_new_route_is_protected_without_asking(seeded: Engine, build: BuildApp) -> None:
    app = build()

    @app.get("/api/forgot-to-protect")
    def forgot() -> dict[str, str]:
        return {"data": "private"}

    with https_client(app) as client:
        assert client.get("/api/forgot-to-protect").status_code == 401


@pytest.fixture
def role_probe(seeded: Engine, build: BuildApp) -> Iterator[TestClient]:
    # No real admin route exists until M8. When one does, add it to the table with Role.ADMIN.
    app = build()

    @app.get("/api/probe/admin")
    def admin_only(_: Annotated[Principal, Depends(require_role(Role.ADMIN))]) -> None:
        return None

    @app.get("/api/probe/reviewer")
    def reviewer_only(_: Annotated[Principal, Depends(require_role(Role.REVIEWER))]) -> None:
        return None

    with https_client(app) as client:
        yield client


def test_reviewer_cannot_call_an_admin_route(role_probe: TestClient) -> None:
    sign_in(role_probe, REVIEWER_EMAIL, REVIEWER_PASSWORD)

    assert role_probe.get("/api/probe/admin").status_code == 403
    assert role_probe.get("/api/probe/reviewer").status_code == 200


def test_admin_can_call_admin_and_reviewer_routes(role_probe: TestClient) -> None:
    sign_in(role_probe, ADMIN_EMAIL, ADMIN_PASSWORD)

    assert role_probe.get("/api/probe/admin").status_code == 200
    assert role_probe.get("/api/probe/reviewer").status_code == 200
