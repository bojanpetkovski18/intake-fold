import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic.alias_generators import to_camel

from intakefold.api.access import SESSION_COOKIE, CurrentUser
from intakefold.api.rate_limit import limit_sign_in
from intakefold.db.models import Role
from intakefold.identity.sessions import Principal, csrf_token_for, sign_in, sign_out
from intakefold.settings import Settings

router = APIRouter(prefix="/auth")


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    # The upper bound keeps an oversized password from costing extra hashing work.
    password: SecretStr = Field(min_length=1, max_length=128)


class UserView(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: uuid.UUID
    email: str
    display_name: str
    role: Role


class SessionView(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    user: UserView
    csrf_token: str


def session_view(principal: Principal, csrf_token: str) -> SessionView:
    user = UserView(
        id=principal.user_id,
        email=principal.email,
        display_name=principal.display_name,
        role=principal.role,
    )
    return SessionView(user=user, csrf_token=csrf_token)


@router.post("/login", dependencies=[Depends(limit_sign_in)])
def login(body: LoginRequest, request: Request, response: Response) -> SessionView:
    settings: Settings = request.app.state.settings
    ttl = timedelta(hours=settings.session_ttl_hours)
    issued = sign_in(
        request.app.state.engine,
        email=body.email,
        password=body.password.get_secret_value(),
        clock=request.app.state.clock,
        ttl=ttl,
    )
    if issued is None:
        raise HTTPException(status_code=401, detail="The email or password is not correct.")
    response.set_cookie(
        SESSION_COOKIE,
        issued.token,
        max_age=int(ttl.total_seconds()),
        path="/api",
        secure=not settings.allow_insecure_cookies,
        httponly=True,
        samesite="strict",
    )
    return session_view(issued.principal, issued.csrf_token)


@router.post("/logout", status_code=204)
def logout(principal: CurrentUser, request: Request, response: Response) -> None:
    settings: Settings = request.app.state.settings
    sign_out(request.app.state.engine, principal)
    response.delete_cookie(
        SESSION_COOKIE,
        path="/api",
        secure=not settings.allow_insecure_cookies,
        httponly=True,
        samesite="strict",
    )


@router.get("/me")
def me(principal: CurrentUser, request: Request) -> SessionView:
    return session_view(principal, csrf_token_for(request.cookies[SESSION_COOKIE]))
