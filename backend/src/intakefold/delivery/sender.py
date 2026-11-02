"""Sends one delivery. The HTTP call happens with no database transaction open."""

import json
import time
import uuid

import httpx2
import structlog
from sqlalchemy import Engine, String, cast, func, select, update
from sqlalchemy.orm import Session

from intakefold.clock import Clock
from intakefold.db.models import DeliveryAttempt, DeliveryStatus, Job, JobStatus, WebhookDelivery
from intakefold.delivery.events import DELIVER_WEBHOOK
from intakefold.delivery.signing import EVENT_ID_HEADER, SIGNATURE_HEADER, signature_header
from intakefold.jobs.queue import ClaimedJob
from intakefold.settings import Settings, WebhookTarget
from intakefold.worker.loop import PermanentJobError

log = structlog.get_logger()


class DeliveryFailed(Exception):
    """Retryable. `code` is stored on the attempt."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def body_of(payload: dict[str, object]) -> bytes:
    # Fixed key order and spacing, so a retry signs and sends the very same bytes.
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def record_attempt(
    engine: Engine,
    delivery_id: uuid.UUID,
    *,
    status_code: int | None,
    duration_ms: int,
    error_code: str | None,
    delivered: bool,
) -> None:
    with Session(engine) as session, session.begin():
        attempts = session.scalar(
            select(func.count())
            .select_from(DeliveryAttempt)
            .where(DeliveryAttempt.delivery_id == delivery_id)
        )
        session.add(
            DeliveryAttempt(
                delivery_id=delivery_id,
                attempt=(attempts or 0) + 1,
                status_code=status_code,
                duration_ms=duration_ms,
                error_code=error_code,
            )
        )
        if delivered:
            session.execute(
                update(WebhookDelivery)
                .where(WebhookDelivery.id == delivery_id)
                .values(status=DeliveryStatus.DELIVERED)
            )


class WebhookSender:
    def __init__(
        self, engine: Engine, clock: Clock, settings: Settings, client: httpx2.Client
    ) -> None:
        self.engine = engine
        self.clock = clock
        self.targets = {target.name: target for target in settings.webhook_targets}
        self.client = client

    def __call__(self, job: ClaimedJob) -> None:
        delivery_id = uuid.UUID(str(job.payload["delivery_id"]))
        with Session(self.engine) as session:
            delivery = session.get(WebhookDelivery, delivery_id)
            if delivery is None or delivery.status is not DeliveryStatus.PENDING:
                return
            target = self.targets.get(delivery.target)
            event_id, payload = delivery.event_id, delivery.payload
        if target is None:
            # Removed from configuration since approval: retrying cannot bring it back.
            raise PermanentJobError("unknown_target")
        self.send(delivery_id, event_id, payload, target)

    def send(
        self,
        delivery_id: uuid.UUID,
        event_id: uuid.UUID,
        payload: dict[str, object],
        target: WebhookTarget,
    ) -> None:
        body = body_of(payload)
        timestamp = int(self.clock.now().timestamp())
        headers = {
            "Content-Type": "application/json",
            EVENT_ID_HEADER: str(event_id),
            SIGNATURE_HEADER: signature_header(target.secret.get_secret_value(), timestamp, body),
        }
        started = time.perf_counter()
        status_code: int | None = None
        error_code: str | None = None
        try:
            response = self.client.post(str(target.url), content=body, headers=headers)
            status_code = response.status_code
            if not response.is_success:
                error_code = f"http_{status_code}"
        except httpx2.TimeoutException:
            error_code = "timeout"
        except httpx2.HTTPError:
            error_code = "connection_error"
        duration_ms = round((time.perf_counter() - started) * 1000)
        record_attempt(
            self.engine,
            delivery_id,
            status_code=status_code,
            duration_ms=duration_ms,
            error_code=error_code,
            delivered=error_code is None,
        )
        log.info(
            "webhook_attempted",
            target=target.name,
            status_code=status_code,
            error_code=error_code,
            duration_ms=duration_ms,
        )
        if error_code is not None:
            raise DeliveryFailed(error_code)


def mark_dead_deliveries(engine: Engine) -> None:
    """Delivery status follows its job, so a dead job shows as a dead delivery."""
    statement = (
        update(WebhookDelivery)
        .where(
            WebhookDelivery.status == DeliveryStatus.PENDING,
            Job.kind == DELIVER_WEBHOOK,
            Job.status == JobStatus.DEAD,
            Job.payload["delivery_id"].astext == cast(WebhookDelivery.id, String),
        )
        .values(status=DeliveryStatus.DEAD)
    )
    with engine.begin() as connection:
        connection.execute(statement)
