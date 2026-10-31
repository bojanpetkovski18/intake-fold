from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from intakefold.api.app import build_app
from intakefold.clock import Clock
from intakefold.db.models import Base, Role
from intakefold.db.seed import seed
from intakefold.settings import Settings

# Same image as compose.yaml, so tests run on what the stack runs.
POSTGRES_IMAGE = (
    "postgres:18.6-alpine@sha256:10a5c69a83035ab5239f5620d708520e8b28f5aa1f2b20143e6024532edadfb5"
)
ALEMBIC_INI = Path(__file__).parents[2] / "alembic.ini"

ORIGIN = "http://127.0.0.1:8180"
REVIEWER_EMAIL = "reviewer@example.com"
ADMIN_EMAIL = "admin@example.com"
REVIEWER_PASSWORD = "reviewer-test-password"  # noqa: S105 - fictional test account
ADMIN_PASSWORD = "admin-test-password"  # noqa: S105 - fictional test account
DEMO_PASSWORDS = {
    Role.REVIEWER: SecretStr(REVIEWER_PASSWORD),
    Role.ADMIN: SecretStr(ADMIN_PASSWORD),
}

BuildApp = Callable[..., FastAPI]


def alembic_config(url: str) -> Config:
    config = Config(ALEMBIC_INI)
    config.attributes["database_url"] = url
    return config


def https_client(app: FastAPI, **options: object) -> TestClient:
    # https, or the client would rightly hold back the Secure session cookie.
    return TestClient(app, base_url="https://testserver", **options)  # pyright: ignore[reportArgumentType]


def sign_in(client: TestClient, email: str, password: str) -> str:
    """Signs the client in and returns its CSRF token."""
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200
    return response.json()["csrfToken"]


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as postgres:
        url = postgres.get_connection_url()
        command.upgrade(alembic_config(url), "head")
        yield url


@pytest.fixture
def engine(database_url: str) -> Iterator[Engine]:
    """A migrated database, emptied before each test."""
    engine = create_engine(database_url, pool_size=24)
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} CASCADE"))
    yield engine
    engine.dispose()


@pytest.fixture
def seeded(engine: Engine) -> Engine:
    with Session(engine) as session, session.begin():
        seed(session, DEMO_PASSWORDS)
    return engine


@pytest.fixture
def build(database_url: str) -> BuildApp:
    def build_test_app(clock: Clock | None = None, **settings: object) -> FastAPI:
        values = {"database_url": database_url, "allowed_origins": ORIGIN} | settings
        return build_app(Settings.model_validate(values), clock)

    return build_test_app
