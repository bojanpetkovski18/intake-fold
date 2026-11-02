import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from intakefold.api.access import Principal, require_role
from intakefold.api.documents import ApiModel
from intakefold.db.models import DeliveryAttempt, DeliveryStatus, Document, Role, WebhookDelivery
from intakefold.delivery.export import export_rows

router = APIRouter()

Reviewer = Annotated[Principal, Depends(require_role(Role.REVIEWER))]


class AttemptView(ApiModel):
    attempt: int
    status_code: int | None
    duration_ms: int | None
    error_code: str | None
    created_at: datetime


class DeliveryView(ApiModel):
    target: str
    event_id: uuid.UUID
    status: DeliveryStatus
    created_at: datetime
    attempts: list[AttemptView]


def deliveries_of(engine: Engine, document_id: uuid.UUID) -> list[DeliveryView] | None:
    with Session(engine) as session:
        if session.get(Document, document_id) is None:
            return None
        deliveries = session.scalars(
            select(WebhookDelivery)
            .where(WebhookDelivery.document_id == document_id)
            .order_by(WebhookDelivery.created_at, WebhookDelivery.target)
        ).all()
        attempts = session.scalars(
            select(DeliveryAttempt)
            .where(DeliveryAttempt.delivery_id.in_([delivery.id for delivery in deliveries]))
            .order_by(DeliveryAttempt.attempt)
        ).all()
        return [
            DeliveryView(
                target=delivery.target,
                event_id=delivery.event_id,
                status=delivery.status,
                created_at=delivery.created_at,
                attempts=[
                    AttemptView.model_validate(attempt, from_attributes=True)
                    for attempt in attempts
                    if attempt.delivery_id == delivery.id
                ],
            )
            for delivery in deliveries
        ]


@router.get("/documents/{document_id}/deliveries")
def deliveries(request: Request, _: Reviewer, document_id: uuid.UUID) -> list[DeliveryView]:
    found = deliveries_of(request.app.state.engine, document_id)
    if found is None:
        raise HTTPException(status_code=404, detail="There is no such document.")
    return found


@router.get("/exports/invoices.csv")
def export_invoices(
    request: Request,
    _: Reviewer,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
) -> StreamingResponse:
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=422, detail="`from` must not be after `to`.")
    return StreamingResponse(
        export_rows(request.app.state.engine, start, end),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="approved-invoices.csv"'},
    )
