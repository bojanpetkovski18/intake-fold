import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from support import FakeClock

from intakefold.clock import SystemClock
from intakefold.db.models import Batch, BatchSource, ExtractionOutcome, WebhookDelivery
from intakefold.db.seed import seed_vendors
from intakefold.documents.storage import Storage
from intakefold.eval.harness import DatabaseNotEmpty, load_labels, run_evaluation
from intakefold.eval.report import PLUMBING_HEADING, write_reports
from intakefold.eval.scoring import Outcome
from intakefold.extraction.mock import MockExtractor
from intakefold.extraction.types import DocumentInput, ExtractionResult
from intakefold.settings import Settings

pytestmark = pytest.mark.integration

LABELED_SET = Path(__file__).parents[3] / "data" / "labeled"
SETTINGS = Settings.model_validate(
    {
        "database_url": "postgresql://unused",
        # Webhooks configured on purpose: an evaluation must still never send one.
        "webhook_targets": [
            {"name": "sink", "url": "http://sink.invalid/hook", "secret": "x" * 32}
        ],
    }
)


@pytest.fixture
def vendors(engine: Engine) -> Engine:
    with Session(engine) as session, session.begin():
        seed_vendors(session)
    return engine


class ShiftedTotals:
    """The mock, except every total is 1.00 out, past the 0.02 tolerance: a countable fault."""

    name = "shifted"

    def __init__(self) -> None:
        self.mock = MockExtractor(LABELED_SET)

    def extract(self, document: DocumentInput) -> ExtractionResult:
        result = self.mock.extract(document)
        if result.data is None or result.data.total is None:
            return result
        total = str(Decimal(result.data.total) + Decimal("1.00"))
        return ExtractionResult(
            ExtractionOutcome.SUCCEEDED,
            self.name,
            data=result.data.model_copy(update={"total": total}),
        )


def run(engine: Engine, tmp_path: Path, extractor: object, set_name: str):
    return run_evaluation(
        engine,
        Storage(tmp_path / "storage"),
        SystemClock(),
        SETTINGS,
        extractor,  # pyright: ignore[reportArgumentType]
        load_labels(LABELED_SET, set_name),
        set_name,
    )


def test_the_mock_scores_the_development_set_through_the_real_pipeline(
    vendors: Engine, tmp_path: Path
) -> None:
    result = run(vendors, tmp_path, MockExtractor(LABELED_SET), "development")

    overall = result.totals.overall()
    assert result.totals.documents == 20
    assert overall[Outcome.WRONG] == overall[Outcome.MISSING] == overall[Outcome.INVENTED] == 0
    assert result.totals.exact == 20
    assert result.routing.false_auto_approvals == 0
    assert result.routing.missed_auto_approvals == 0
    assert result.input_tokens == 0
    assert result.estimated_cost_usd == 0
    assert result.models == []
    with Session(vendors) as session:
        batch = session.scalars(select(Batch)).one()
        assert batch.source is BatchSource.EVAL
        assert batch.doc_cap == 20
        assert session.scalars(select(WebhookDelivery)).all() == []


def test_a_known_perturbation_is_counted_exactly(vendors: Engine, tmp_path: Path) -> None:
    result = run(vendors, tmp_path, ShiftedTotals(), "development")

    totals = result.totals.by_field["total"]
    assert totals[Outcome.WRONG] == 20
    assert totals[Outcome.CORRECT] == 0
    other = {name: counts for name, counts in result.totals.by_field.items() if name != "total"}
    assert all(counts[Outcome.WRONG] == 0 for counts in other.values())
    assert result.totals.exact == 0
    # The total no longer reconciles, so all 8 documents the labels auto-approve go to review.
    assert result.routing.false_auto_approvals == 0
    assert result.routing.missed_auto_approvals == 8


def test_injection_pairs_are_compared(vendors: Engine, tmp_path: Path) -> None:
    result = run(vendors, tmp_path, MockExtractor(LABELED_SET), "injection")

    assert len(result.pairs) == 8
    assert all(pair.changed_fields == [] for pair in result.pairs)
    assert all(pair.injected_flagged is True for pair in result.pairs)
    assert all(pair.clean_flagged is False for pair in result.pairs)
    assert all(pair.injected_status == "needs_review" for pair in result.pairs)
    # D-059: the injected twin is a real duplicate of its clean twin, and the label expects it.
    assert result.routing.false_auto_approvals == 0


def test_an_evaluation_refuses_a_database_with_documents(vendors: Engine, tmp_path: Path) -> None:
    run(vendors, tmp_path, MockExtractor(LABELED_SET), "development")

    with pytest.raises(DatabaseNotEmpty):
        run(vendors, tmp_path, MockExtractor(LABELED_SET), "development")


def test_reports_are_written_dated_with_the_plumbing_heading(
    vendors: Engine, tmp_path: Path
) -> None:
    result = run(vendors, tmp_path, MockExtractor(LABELED_SET), "development")

    markdown, data = write_reports(result, tmp_path / "reports")

    today = result.finished_at.date().isoformat()
    assert markdown.name == f"{today}-mock-none-development.md"
    assert markdown.read_text(encoding="utf-8").splitlines()[0] == PLUMBING_HEADING
    payload = json.loads(data.read_text(encoding="utf-8"))
    assert payload["plumbing_test"] is True
    assert payload["documents"] == 20
    assert payload["field_accuracy"] == "1.0000"


def test_the_batch_token_cap_applies_to_an_evaluation(vendors: Engine, tmp_path: Path) -> None:
    clock = FakeClock()
    result = run_evaluation(
        vendors,
        Storage(tmp_path / "storage"),
        clock,
        SETTINGS.model_copy(update={"batch_token_cap": 1}),
        MockExtractor(LABELED_SET),
        load_labels(LABELED_SET, "development"),
        "development",
    )

    with Session(vendors) as session:
        assert session.scalars(select(Batch)).one().token_cap == 1
    assert result.totals.documents == 20
