from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import Engine

from intakefold.clock import Clock
from intakefold.db.models import Role
from intakefold.identity.sessions import Principal, authenticate, csrf_token_matches
from intakefold.settings import Settings

SESSION_COOKIE = "intakefold_session"
CSRF_HEADER = "X-CSRF-Token"

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Everything else needs a session. tests/integration/test_route_table.py must list new routes.
PUBLIC_ROUTES = frozenset({("GET", "/api/health"), ("POST", "/api/auth/login")})
ROLE_RANK = {Role.REVIEWER: 1, Role.ADMIN: 2}


def enforce_access(request: Request) -> None:
    """Runs on every route, so a new route is protected without having to ask for it."""
    settings: Settings = request.app.state.settings
    unsafe = request.method not in SAFE_METHODS

    if unsafe and request.headers.get("origin") not in settings.allowed_origins:
        raise HTTPException(status_code=403, detail="This origin is not allowed.")
    # The request path, because FastAPI's matched route omits the prefix of an included router.
    # That is safe here: no public route has path parameters.
    if (request.method, request.url.path) in PUBLIC_ROUTES:
        return

    token = request.cookies.get(SESSION_COOKIE)
    engine: Engine = request.app.state.engine
    clock: Clock = request.app.state.clock
    principal = authenticate(engine, token, clock) if token else None
    if principal is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    if unsafe and not csrf_token_matches(principal, request.headers.get(CSRF_HEADER, "")):
        raise HTTPException(status_code=403, detail="The CSRF token is missing or not valid.")
    request.state.principal = principal


def require_user(request: Request) -> Principal:
    principal: Principal | None = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return principal


CurrentUser = Annotated[Principal, Depends(require_user)]


def require_role(role: Role) -> Callable[[Principal], Principal]:
    def check_role(principal: CurrentUser) -> Principal:
        if ROLE_RANK[principal.role] < ROLE_RANK[role]:
            raise HTTPException(status_code=403, detail="Your role cannot do this.")
        return principal

    return check_role
