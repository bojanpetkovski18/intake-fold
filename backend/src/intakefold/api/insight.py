import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from intakefold.api.access import Principal, require_role
from intakefold.api.documents import ApiModel
from intakefold.audit.insight import metrics, run_log
from intakefold.db.models import Role, StepStatus

router = APIRouter()

Reviewer = Annotated[Principal, Depends(require_role(Role.REVIEWER))]


def decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:f}"


class StepView(ApiModel):
    step: str
    attempt: int
    status: StepStatus
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    extractor: str | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    estimated_cost_usd: str | None
    error_code: str | None


class EventView(ApiModel):
    action: str
    field: str | None
    old_value: str | None
    new_value: str | None
    actor_name: str | None
    created_at: datetime


class RunLogView(ApiModel):
    steps: list[StepView]
    events: list[EventView]


class MetricsRowView(ApiModel):
    extractor: str
    processed: int
    auto_approved: int
    went_to_review: int
    failed: int
    auto_approved_share: str
    review_share: str
    failure_share: str
    average_seconds: str | None


class MetricsView(ApiModel):
    rows: list[MetricsRowView]


@router.get("/documents/{document_id}/run-log")
def document_run_log(request: Request, _: Reviewer, document_id: uuid.UUID) -> RunLogView:
    log = run_log(request.app.state.engine, document_id)
    if log is None:
        raise HTTPException(status_code=404, detail="There is no such document.")
    return RunLogView(
        steps=[
            StepView(
                step=step.step,
                attempt=step.attempt,
                status=step.status,
                started_at=step.started_at,
                finished_at=step.finished_at,
                duration_ms=step.duration_ms,
                extractor=step.extractor,
                model=step.model,
                input_tokens=step.input_tokens,
                output_tokens=step.output_tokens,
                cache_read_tokens=step.cache_read_tokens,
                cache_write_tokens=step.cache_write_tokens,
                estimated_cost_usd=decimal_text(step.estimated_cost_usd),
                error_code=step.error_code,
            )
            for step in log.steps
        ],
        events=[EventView.model_validate(event, from_attributes=True) for event in log.events],
    )


@router.get("/metrics")
def all_metrics(request: Request, _: Reviewer) -> MetricsView:
    return MetricsView(
        rows=[
            MetricsRowView(
                extractor=row.extractor,
                processed=row.processed,
                auto_approved=row.auto_approved,
                went_to_review=row.went_to_review,
                failed=row.failed,
                auto_approved_share=f"{row.auto_approved_share:f}",
                review_share=f"{row.review_share:f}",
                failure_share=f"{row.failure_share:f}",
                average_seconds=decimal_text(row.average_seconds),
            )
            for row in metrics(request.app.state.engine)
        ]
    )
