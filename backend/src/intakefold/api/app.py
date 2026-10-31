from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from intakefold.api import health
from intakefold.api.middleware import RequestContextMiddleware
from intakefold.api.problems import register_problem_handlers
from intakefold.db import build_engine
from intakefold.logging import configure_logging
from intakefold.settings import ConfigurationError, Settings, load_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    yield
    app.state.engine.dispose()


def build_app(settings: Settings) -> FastAPI:
    configure_logging(settings.log_level)
    # The interactive docs are off: they need scripts the CSP blocks, and are not public.
    app = FastAPI(
        title="Intakefold", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.engine = build_engine(settings)
    app.add_middleware(RequestContextMiddleware, hsts=settings.environment == "production")
    register_problem_handlers(app)
    app.include_router(health.router, prefix="/api")
    return app


def create_app() -> FastAPI:
    """Entry point for `uvicorn --factory intakefold.api.app:create_app`."""
    try:
        return build_app(load_settings())
    except ConfigurationError as error:
        structlog.get_logger().critical("startup_failed", reason=str(error))
        raise SystemExit(str(error)) from None
