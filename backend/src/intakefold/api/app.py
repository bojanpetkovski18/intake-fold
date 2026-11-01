from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI

from intakefold.api import auth, documents, health
from intakefold.api.access import enforce_access
from intakefold.api.middleware import RequestContextMiddleware
from intakefold.api.problems import register_problem_handlers
from intakefold.api.rate_limit import RateLimiter
from intakefold.clock import Clock, SystemClock
from intakefold.db.engine import build_engine
from intakefold.documents.storage import Storage
from intakefold.logging import configure_logging
from intakefold.settings import ConfigurationError, Settings, load_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    yield
    app.state.engine.dispose()


def build_app(settings: Settings, clock: Clock | None = None) -> FastAPI:
    configure_logging(settings.log_level)
    # The interactive docs are off: they need scripts the CSP blocks, and are not public.
    app = FastAPI(
        title="Intakefold",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
        dependencies=[Depends(enforce_access)],
    )
    app.state.settings = settings
    app.state.clock = clock or SystemClock()
    app.state.engine = build_engine(settings)
    app.state.storage = Storage(settings.storage_dir)
    app.state.sign_in_limiter = RateLimiter(settings.sign_in_rate_limit)
    app.state.upload_limiter = RateLimiter(settings.upload_rate_limit)
    app.add_middleware(RequestContextMiddleware, hsts=settings.environment == "production")
    register_problem_handlers(app)
    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(documents.router, prefix="/api")
    return app


def create_app() -> FastAPI:
    """Entry point for `uvicorn --factory intakefold.api.app:create_app`."""
    try:
        return build_app(load_settings())
    except ConfigurationError as error:
        structlog.get_logger().critical("startup_failed", reason=str(error))
        raise SystemExit(str(error)) from None
