"""Runs a labeled set through the real pipeline as one evaluation batch, then scores it."""

import json
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from functools import partial
from pathlib import Path

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from intakefold.clock import Clock
from intakefold.db.models import (
    BatchSource,
    Document,
    Invoice,
    Job,
    JobStatus,
    LineItem,
    RunStep,
)
from intakefold.documents.intake import Refused, prepare_file, record_batch
from intakefold.documents.storage import Storage
from intakefold.eval.scoring import (
    DocumentScore,
    Fields,
    Routing,
    RoutingTotals,
    Totals,
    injection_changes,
    score_document,
)
from intakefold.extraction.types import Extractor
from intakefold.settings import Settings
from intakefold.worker.handlers import build_handlers, on_job_dead
from intakefold.worker.loop import Worker

SETS = ("development", "held_out", "injection")
POLL_SECONDS = 0.5
RUN_TIMEOUT_SECONDS = 3600


class DatabaseNotEmpty(Exception):
    """Uploads deduplicate by content, so a reused database would score nothing new."""


@dataclass(frozen=True)
class Label:
    id: str
    split: str
    path: Path
    fields: Fields
    expected_outcome: str
    pair_id: str | None
    injected: bool


@dataclass(frozen=True)
class DocumentResult:
    label: Label
    actual: Fields | None
    status: str
    flagged_injection: bool | None
    score: DocumentScore


@dataclass(frozen=True)
class PairResult:
    pair_id: str
    changed_fields: list[str]
    injected_flagged: bool | None
    clean_flagged: bool | None
    injected_status: str


@dataclass
class EvalResult:
    set_name: str
    extractor: str
    models: list[str]
    started_at: datetime
    finished_at: datetime
    documents: list[DocumentResult] = field(default_factory=list[DocumentResult])
    totals: Totals = field(default_factory=Totals)
    routing: RoutingTotals = field(default_factory=RoutingTotals)
    pairs: list[PairResult] = field(default_factory=list[PairResult])
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: Decimal = Decimal(0)


def load_labels(labels_dir: Path, set_name: str) -> list[Label]:
    labels: list[Label] = []
    for path in sorted((labels_dir / set_name).glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        labels.append(
            Label(
                id=raw["id"],
                split=raw["split"],
                path=path.parent / raw["file"],
                fields=raw["fields"],
                expected_outcome=raw["expected_routing"]["outcome"],
                pair_id=raw["pair_id"],
                injected=raw["contains_embedded_instructions"],
            )
        )
    # Originals before duplicates and clean twins before injected ones, as the labels assume.
    return labels


def first_documents(
    labels: list[Label], set_name: str, limit: int | None
) -> tuple[list[Label], str]:
    """A smoke run's labels and name. The name carries the limit, so its report is never
    mistaken for the whole set's."""
    if limit is None:
        return labels, set_name
    return labels[:limit], f"{set_name}-first{limit}"


def ensure_empty(engine: Engine) -> None:
    with Session(engine) as session:
        if session.scalar(select(func.count()).select_from(Document)):
            raise DatabaseNotEmpty


def invoice_fields(session: Session, document_id: uuid.UUID) -> tuple[Fields | None, bool | None]:
    invoice = session.scalar(select(Invoice).where(Invoice.document_id == document_id))
    if invoice is None:
        return None, None
    lines = session.scalars(
        select(LineItem).where(LineItem.invoice_id == invoice.id).order_by(LineItem.position)
    )
    fields: Fields = {
        "document_type": invoice.document_type.value,
        "vendor_name": invoice.vendor_name,
        "invoice_number": invoice.invoice_number,
        "issue_date": invoice.issue_date,
        "due_date": invoice.due_date,
        "currency": invoice.currency,
        "subtotal": invoice.subtotal,
        "tax_total": invoice.tax_total,
        "adjustments_total": invoice.adjustments_total,
        "total": invoice.total,
        "line_items": [
            {
                "description": line.description,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "amount": line.amount,
            }
            for line in lines
        ],
    }
    return fields, invoice.contains_embedded_instructions


def drain(engine: Engine, worker: Worker) -> None:
    """Runs the worker until no job is left. Retries wait out their backoff, with a deadline."""
    deadline = time.monotonic() + RUN_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if worker.run_once():
            continue
        with Session(engine) as session:
            open_jobs = session.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)))
            )
        if not open_jobs:
            return
        time.sleep(POLL_SECONDS)
    raise TimeoutError("The evaluation did not finish within the time limit.")


def run_evaluation(
    engine: Engine,
    storage: Storage,
    clock: Clock,
    settings: Settings,
    extractor: Extractor,
    labels: list[Label],
    set_name: str,
) -> EvalResult:
    ensure_empty(engine)
    # Its own batch and caps, and no webhooks: an evaluation must not reach downstream systems.
    eval_settings = settings.model_copy(
        update={"webhook_targets": (), "max_batch_files": len(labels)}
    )
    started_at = clock.now()
    prepared = [
        prepare_file(
            engine,
            storage,
            eval_settings,
            raw_filename=label.path.name,
            data=label.path.read_bytes(),
        )
        for label in labels
    ]
    _, file_results = record_batch(
        engine,
        storage,
        clock,
        eval_settings,
        user_id=None,
        prepared=prepared,
        source=BatchSource.EVAL,
    )
    worker = Worker(
        engine,
        build_handlers(engine, storage, clock, extractor, eval_settings),
        clock=clock,
        on_job_dead=partial(on_job_dead, engine, clock),
        poll_seconds=0,
    )
    drain(engine, worker)

    result = EvalResult(set_name, extractor.name, [], started_at, clock.now())
    by_label: dict[str, DocumentResult] = {}
    with Session(engine) as session:
        for label, prepared_file, file_result in zip(labels, prepared, file_results, strict=True):
            if isinstance(prepared_file, Refused) or isinstance(file_result, Refused):
                actual, flagged, status = None, None, "refused"
            else:
                document = session.get_one(Document, file_result.document_id)
                actual, flagged = invoice_fields(session, document.id)
                status = document.status.value
            document_result = DocumentResult(
                label, actual, status, flagged, score_document(label.fields, actual)
            )
            by_label[label.id] = document_result
            result.documents.append(document_result)
            result.totals.add(document_result.score)
            result.routing.add(Routing(label.expected_outcome, status))
        ids = [r.document_id for r in file_results if not isinstance(r, Refused)]
        usage = session.execute(
            select(
                func.coalesce(func.sum(RunStep.input_tokens), 0),
                func.coalesce(func.sum(RunStep.output_tokens), 0),
                func.coalesce(func.sum(RunStep.estimated_cost_usd), 0),
            ).where(RunStep.document_id.in_(ids))
        ).one()
        # coalesce makes these zero when there are no rows; the types cannot see that.
        result.input_tokens = usage[0] or 0
        result.output_tokens = usage[1] or 0
        result.estimated_cost_usd = usage[2] or Decimal(0)
        result.models = sorted(
            model
            for model in session.scalars(
                select(RunStep.model)
                .where(RunStep.document_id.in_(ids), RunStep.model.is_not(None))
                .distinct()
            )
            if model is not None
        )
    result.pairs = pair_results(by_label.values())
    return result


def pair_results(documents: Iterable[DocumentResult]) -> list[PairResult]:
    twins: dict[str, dict[bool, DocumentResult]] = {}
    for document in documents:
        if document.label.pair_id is not None:
            twins.setdefault(document.label.pair_id, {})[document.label.injected] = document
    pairs: list[PairResult] = []
    for pair_id, twin in sorted(twins.items()):
        clean, injected = twin.get(False), twin.get(True)
        if clean is None or injected is None:
            continue
        pairs.append(
            PairResult(
                pair_id=pair_id,
                changed_fields=injection_changes(clean.actual, injected.actual),
                injected_flagged=injected.flagged_injection,
                clean_flagged=clean.flagged_injection,
                injected_status=injected.status,
            )
        )
    return pairs
