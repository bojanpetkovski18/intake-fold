from alembic import context
from sqlalchemy import create_engine

from intakefold.db.models import Base
from intakefold.settings import load_settings


def database_url() -> str:
    # Tests pass the URL directly. It is not put in the ini, which would treat % as syntax.
    url = context.config.attributes.get("database_url")
    if isinstance(url, str):
        return url
    return load_settings().database_url.get_secret_value()


def run_migrations() -> None:
    engine = create_engine(database_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations()
