from collections import Counter
from collections.abc import Iterator
from functools import partial
from pathlib import Path

import pytest
from conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    ORIGIN,
    REVIEWER_EMAIL,
    REVIEWER_PASSWORD,
    BuildApp,
    https_client,
    sign_in,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fixtures_files import pdf_bytes
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session
from support import FakeClock

from intakefold.db.models import (
    AuditEvent,
    Base,
    Batch,
    BatchSource,
    Document,
    DocumentStatus,
    User,
    Vendor,
)
from intakefold.db.models import Session as SessionRow
from intakefold.db.seed import main as seed_main
from intakefold.demo import DOCUMENT_TABLES, seed_demo_batch, seed_demo_if_empty
from intakefold.documents.storage import Storage
from intakefold.eval.harness import drain, load_labels
from intakefold.extraction.mock import MockExtractor
from intakefold.settings import Settings
from intakefold.worker.handlers import build_handlers, on_job_dead
from intakefold.worker.loop import Worker

pytestmark = pytest.mark.integration

LABELED_SET = Path(__file__).parents[3] / "data" / "labeled"
DEMO = {
    "demo_mode": True,
    "demo_reviewer_password": REVIEWER_PASSWORD,
    "demo_admin_password": ADMIN_PASSWORD,
    "labels_dir": LABELED_SET,
}
# Uploads deduplicate by content, so the batch has one document per distinct file.
DEMO_DOCUMENTS = len({label.path.read_bytes() for label in load_labels(LABELED_SET, "development")})


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def demo_app(seeded: Engine, build: BuildApp, clock: FakeClock) -> FastAPI:
    return build(clock, upload_rate_limit="1000/minute", **DEMO)


@pytest.fixture
def admin(demo_app: FastAPI) -> Iterator[tuple[TestClient, str]]:
    with https_client(demo_app) as client:
        yield client, sign_in(client, ADMIN_EMAIL, ADMIN_PASSWORD)


def headers(csrf: str) -> dict[str, str]:
    return {"Origin": ORIGIN, "X-CSRF-Token": csrf}


def process(app: FastAPI) -> None:
    """What the worker process does in the running stack. The mock never fails, so no retries."""
    state = app.state
    settings: Settings = state.settings
    extractor = MockExtractor(LABELED_SET)
    worker = Worker(
        state.engine,
        build_handlers(state.engine, state.storage, state.clock, extractor, settings),
        clock=state.clock,
        on_job_dead=partial(on_job_dead, state.engine, state.clock),
        poll_seconds=0,
    )
    drain(state.engine, worker)


def statuses(engine: Engine) -> Counter[DocumentStatus]:
    with Session(engine) as session:
        return Counter(session.scalars(select(Document.status)))


def count(engine: Engine, model: type[Base]) -> int:
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(model)) or 0


def stored_files(app: FastAPI) -> set[Path]:
    root: Path = app.state.storage.root
    return {path for path in root.rglob("*") if path.is_file()}


def test_every_table_is_either_reset_or_kept_on_purpose() -> None:
    kept = {User.__tablename__, SessionRow.__tablename__, Vendor.__tablename__}

    assert set(DOCUMENT_TABLES) | kept == set(Base.metadata.tables)
    assert not set(DOCUMENT_TABLES) & kept


def test_demo_accounts_are_public_in_demo_mode(demo_app: FastAPI) -> None:
    with https_client(demo_app) as client:
        response = client.get("/api/demo")

    assert response.status_code == 200
    assert response.json() == {
        "accounts": [
            {"email": REVIEWER_EMAIL, "role": "reviewer", "password": REVIEWER_PASSWORD},
            {"email": ADMIN_EMAIL, "role": "admin", "password": ADMIN_PASSWORD},
        ]
    }


def test_demo_accounts_are_hidden_outside_demo_mode(seeded: Engine, build: BuildApp) -> None:
    app = build(demo_reviewer_password=REVIEWER_PASSWORD, demo_admin_password=ADMIN_PASSWORD)
    with https_client(app) as client:
        response = client.get("/api/demo")

    assert response.status_code == 404
    assert REVIEWER_PASSWORD not in response.text


def test_the_session_says_whether_demo_mode_is_on(
    demo_app: FastAPI, seeded: Engine, build: BuildApp
) -> None:
    with https_client(demo_app) as client:
        sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
        assert client.get("/api/auth/me").json()["demoMode"] is True
    with https_client(build()) as client:
        sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
        assert client.get("/api/auth/me").json()["demoMode"] is False


def test_reset_is_refused_outside_demo_mode(seeded: Engine, build: BuildApp) -> None:
    with https_client(build()) as client:
        csrf = sign_in(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        response = client.post("/api/demo/reset", headers=headers(csrf))

    assert response.status_code == 404
    assert count(seeded, Batch) == 0


def test_reset_is_refused_to_a_reviewer_in_demo_mode(demo_app: FastAPI, seeded: Engine) -> None:
    with https_client(demo_app) as client:
        csrf = sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
        response = client.post("/api/demo/reset", headers=headers(csrf))

    assert response.status_code == 403
    assert count(seeded, Batch) == 0


def test_reset_restores_the_seed_state(
    demo_app: FastAPI, admin: tuple[TestClient, str], seeded: Engine, clock: FakeClock
) -> None:
    client, csrf = admin
    state = demo_app.state
    seed_demo_batch(seeded, state.storage, clock, state.settings, actor=None)
    process(demo_app)
    seeded_statuses = statuses(seeded)
    seeded_files = len(stored_files(demo_app))
    # Change the demo: an extra upload and a reviewer decision with its audit event.
    extra = client.post(
        "/api/documents",
        files=[("files", ("extra.pdf", pdf_bytes(seed=7)))],
        headers=headers(csrf),
    )
    assert extra.status_code == 201
    process(demo_app)
    in_review = next(
        document
        for document in client.get("/api/documents", params={"status": "needs_review"}).json()[
            "items"
        ]
    )
    rejected = client.post(
        f"/api/documents/{in_review['id']}/reject",
        json={"version": 1, "reason": "Demo change."},
        headers=headers(csrf),
    )
    assert rejected.status_code == 200
    assert count(seeded, AuditEvent) > 0
    users, vendors = count(seeded, User), count(seeded, Vendor)

    response = client.post("/api/demo/reset", headers=headers(csrf))

    assert response.status_code == 202
    assert response.json() == {"queued": DEMO_DOCUMENTS}
    assert statuses(seeded) == Counter({DocumentStatus.QUEUED: DEMO_DOCUMENTS})
    with Session(seeded) as session:
        # The old trail is gone; what remains is one upload event per new document.
        actions = Counter(session.scalars(select(AuditEvent.action)))
        batch = session.scalars(select(Batch)).one()
        admin_id = session.scalar(select(User.id).where(User.email == ADMIN_EMAIL))
    assert actions == Counter({"document_uploaded": DEMO_DOCUMENTS})
    assert batch.source is BatchSource.DEMO
    assert batch.created_by == admin_id
    # The extra upload and every rendered page are gone; only the new originals remain.
    assert len(stored_files(demo_app)) == DEMO_DOCUMENTS
    # Accounts and vendors are kept, and the admin is still signed in.
    assert (count(seeded, User), count(seeded, Vendor)) == (users, vendors)
    assert client.get("/api/auth/me").status_code == 200

    process(demo_app)

    assert statuses(seeded) == seeded_statuses
    assert len(stored_files(demo_app)) == seeded_files


def test_the_seed_command_adds_the_demo_batch_only_once(
    demo_app: FastAPI, seeded: Engine, clock: FakeClock
) -> None:
    state = demo_app.state
    storage: Storage = state.storage

    first = seed_demo_if_empty(seeded, storage, clock, state.settings)
    second = seed_demo_if_empty(seeded, storage, clock, state.settings)

    assert (first, second) == (DEMO_DOCUMENTS, 0)
    assert count(seeded, Batch) == 1
    assert count(seeded, SessionRow) == 0


def test_the_seed_command_runs_the_demo_seed_in_demo_mode(
    engine: Engine,
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name, value in {
        "DATABASE_URL": database_url,
        "DEMO_MODE": "true",
        "DEMO_REVIEWER_PASSWORD": REVIEWER_PASSWORD,
        "DEMO_ADMIN_PASSWORD": ADMIN_PASSWORD,
        "LABELS_DIR": str(LABELED_SET),
        "STORAGE_DIR": str(tmp_path / "storage"),
        "EXTRACTOR": "mock",
    }.items():
        monkeypatch.setenv(name, value)

    seed_main()
    seed_main()

    assert count(engine, Batch) == 1
    assert count(engine, Document) == DEMO_DOCUMENTS
    assert count(engine, User) == 2
    assert capsys.readouterr().out.splitlines() == [
        f"Demo mode: queued {DEMO_DOCUMENTS} documents for the worker.",
        "Demo mode: queued 0 documents for the worker.",
    ]
