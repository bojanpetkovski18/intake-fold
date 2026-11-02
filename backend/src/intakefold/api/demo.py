from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from intakefold.api.access import Principal, require_role
from intakefold.api.documents import ApiModel
from intakefold.db.models import Role
from intakefold.demo import demo_accounts, reset_demo
from intakefold.settings import Settings

router = APIRouter(prefix="/demo")

Admin = Annotated[Principal, Depends(require_role(Role.ADMIN))]


class DemoAccountView(ApiModel):
    email: str
    role: Role
    password: str


class DemoView(ApiModel):
    accounts: list[DemoAccountView]


class ResetView(ApiModel):
    queued: int


def require_demo_mode(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="Demo mode is off.")
    return settings


DemoSettings = Annotated[Settings, Depends(require_demo_mode)]


@router.get("")
def demo(settings: DemoSettings) -> DemoView:
    """Public, for the sign-in page. Only demo mode has passwords to show."""
    return DemoView(
        accounts=[
            DemoAccountView.model_validate(account, from_attributes=True)
            for account in demo_accounts(settings)
        ]
    )


@router.post("/reset", status_code=202)
def reset(request: Request, principal: Admin, settings: DemoSettings) -> ResetView:
    state = request.app.state
    queued = reset_demo(state.engine, state.storage, state.clock, settings, actor=principal.user_id)
    return ResetView(queued=queued)
