import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Engine, insert, update
from sqlalchemy.orm import Session

from intakefold.clock import Clock
from intakefold.db.models import AuditEvent, RunStep, StepStatus, new_id


def record_audit_event(
    session: Session,
    *,
    document_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    action: str,
    field: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
) -> None:
    """Adds to the caller's transaction, so the record commits with the change it describes."""
    session.add(
        AuditEvent(
            document_id=document_id,
            actor_user_id=actor_user_id,
            action=action,
            field=field,
            old_value=old_value,
            new_value=new_value,
        )
    )


@dataclass(slots=True)
class StepDetails:
    """Filled in by the step's code. Left empty for steps with no model call."""

    extractor: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    estimated_cost_usd: Decimal | None = None


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    return round((finished_at - started_at).total_seconds() * 1000)


@contextmanager
def run_step(
    engine: Engine,
    clock: Clock,
    *,
    document_id: uuid.UUID,
    job_id: uuid.UUID | None,
    attempt: int,
    step: str,
) -> Generator[StepDetails]:
    """Records a pipeline step in its own transactions.

    The row is committed before the work starts, so a crash leaves a visible `running` step.
    """
    step_id = new_id()
    started_at = clock.now()
    with engine.begin() as connection:
        connection.execute(
            insert(RunStep).values(
                id=step_id,
                document_id=document_id,
                job_id=job_id,
                attempt=attempt,
                step=step,
                status=StepStatus.RUNNING,
                started_at=started_at,
            )
        )

    details = StepDetails()

    def finish(status: StepStatus, error_code: str | None) -> None:
        finished_at = clock.now()
        with engine.begin() as connection:
            connection.execute(
                update(RunStep)
                .where(RunStep.id == step_id)
                .values(
                    status=status,
                    finished_at=finished_at,
                    duration_ms=_duration_ms(started_at, finished_at),
                    error_code=error_code,
                    extractor=details.extractor,
                    model=details.model,
                    input_tokens=details.input_tokens,
                    output_tokens=details.output_tokens,
                    cache_read_tokens=details.cache_read_tokens,
                    cache_write_tokens=details.cache_write_tokens,
                    estimated_cost_usd=details.estimated_cost_usd,
                )
            )

    try:
        yield details
    except Exception as error:
        finish(StepStatus.FAILED, type(error).__name__)
        raise
    finish(StepStatus.SUCCEEDED, None)
