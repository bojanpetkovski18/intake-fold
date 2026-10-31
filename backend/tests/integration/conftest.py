from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from testcontainers.community.postgres import PostgresContainer

from intakefold.db.models import Base

# Same image as compose.yaml, so tests run on what the stack runs.
POSTGRES_IMAGE = (
    "postgres:18.6-alpine@sha256:10a5c69a83035ab5239f5620d708520e8b28f5aa1f2b20143e6024532edadfb5"
)
ALEMBIC_INI = Path(__file__).parents[2] / "alembic.ini"


def alembic_config(url: str) -> Config:
    config = Config(ALEMBIC_INI)
    config.attributes["database_url"] = url
    return config


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
