import structlog
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

log = structlog.get_logger()

router = APIRouter()


def database_is_reachable(engine: Engine) -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        # The type only: the message of a connection error can contain the URL.
        log.warning("database_unreachable", error_type=type(error).__name__)
        return False
    return True


@router.get("/health")
def health(request: Request) -> dict[str, str]:
    if not database_is_reachable(request.app.state.engine):
        raise HTTPException(status_code=503, detail="The database is not reachable.")
    return {"status": "ok", "database": "ok"}
