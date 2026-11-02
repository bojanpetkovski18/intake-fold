import base64
import binascii
import json
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from intakefold.api.access import Principal, require_role
from intakefold.api.documents import ApiModel
from intakefold.db.models import Role
from intakefold.jobs.dead_letters import (
    JobNotDead,
    JobNotFound,
    list_dead_jobs,
    retry_dead_job,
)

router = APIRouter(prefix="/jobs")

Reviewer = Annotated[Principal, Depends(require_role(Role.REVIEWER))]
Admin = Annotated[Principal, Depends(require_role(Role.ADMIN))]


class JobView(ApiModel):
    id: uuid.UUID
    kind: str
    attempts: int
    max_attempts: int
    last_error: str | None
    updated_at: datetime
    document_id: uuid.UUID | None
    filename: str | None


class JobList(ApiModel):
    items: list[JobView]
    next_cursor: str | None


def encode_cursor(position: tuple[datetime, uuid.UUID]) -> str:
    updated_at, job_id = position
    raw = json.dumps([updated_at.isoformat(), str(job_id)]).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.b64decode(cursor.encode(), altchars=b"-_", validate=True)
        text, job_id = json.loads(raw)
        return datetime.fromisoformat(text), uuid.UUID(job_id)
    except binascii.Error, ValueError, TypeError:
        raise HTTPException(status_code=400, detail="The cursor is not valid.") from None


@router.get("")
def list_jobs(
    request: Request,
    _: Reviewer,
    status: Literal["dead"] = "dead",
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
) -> JobList:
    after = decode_cursor(cursor) if cursor is not None else None
    page = list_dead_jobs(request.app.state.engine, limit=limit, after=after)
    return JobList(
        items=[JobView.model_validate(item, from_attributes=True) for item in page.items],
        next_cursor=encode_cursor(page.next_position) if page.next_position else None,
    )


@router.post("/{job_id}/retry", status_code=202)
def retry(request: Request, principal: Admin, job_id: uuid.UUID) -> dict[str, str]:
    try:
        retry_dead_job(request.app.state.engine, job_id, principal.user_id, request.app.state.clock)
    except JobNotFound:
        raise HTTPException(status_code=404, detail="There is no such job.") from None
    except JobNotDead:
        raise HTTPException(status_code=409, detail="This job is not dead.") from None
    return {"status": "queued"}
