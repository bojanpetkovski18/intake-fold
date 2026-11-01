import base64
import json
import threading
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import httpx2
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
from fastapi.testclient import TestClient
from fixtures_files import jpeg_bytes, pdf_bytes, png_bytes
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session
from support import FakeClock

from intakefold.db.models import AuditEvent, Batch, BatchSource, Document, DocumentStatus, Job

pytestmark = pytest.mark.integration

DOCUMENTS = "/api/documents"
UploadPart = tuple[str, tuple[str, bytes, str]]


def part(filename: str, data: bytes, content_type: str = "application/octet-stream") -> UploadPart:
    return ("files", (filename, data, content_type))


def post_files(client: TestClient, csrf_token: str, *files: UploadPart) -> httpx2.Response:
    return client.post(
        DOCUMENTS, files=files, headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_token}
    )


def count(engine: Engine, model: type[Document] | type[Job] | type[Batch]) -> int:
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(model)) or 0


def originals(tmp_path: Path) -> list[Path]:
    directory = tmp_path / "storage" / "originals"
    return list(directory.iterdir()) if directory.exists() else []


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def client(seeded: Engine, build: BuildApp, clock: FakeClock) -> Iterator[TestClient]:
    with https_client(build(clock)) as client:
        yield client


@pytest.fixture
def csrf(client: TestClient) -> str:
    return sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)


def test_upload_creates_a_document_a_job_and_an_audit_event(
    client: TestClient, csrf: str, seeded: Engine
) -> None:
    response = post_files(client, csrf, part("invoice.pdf", pdf_bytes(pages=2)))

    assert response.status_code == 201
    body = response.json()
    file = body["files"][0]
    assert file["deduplicated"] is False
    with Session(seeded) as session:
        document = session.scalars(select(Document)).one()
        job = session.scalars(select(Job)).one()
        batch = session.scalars(select(Batch)).one()
        event = session.scalars(select(AuditEvent)).one()
    assert str(document.id) == file["documentId"]
    assert document.status is DocumentStatus.QUEUED
    assert document.page_count == 2
    assert document.media_type == "application/pdf"
    assert job.kind == "process_document"
    assert job.payload == {"document_id": str(document.id)}
    assert str(batch.id) == body["batchId"]
    assert batch.source is BatchSource.UPLOAD
    assert batch.doc_cap == 25
    assert event.action == "document_uploaded"
    assert event.actor_user_id == batch.created_by


def test_document_named_pdf_with_other_content_is_refused(
    client: TestClient, csrf: str, seeded: Engine, tmp_path: Path
) -> None:
    response = post_files(client, csrf, part("invoice.pdf", b"not a pdf at all", "application/pdf"))

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["errors"] == [
        {
            "filename": "invoice.pdf",
            "deduplicated": False,
            "code": "unsupported_type",
            "detail": "Only PDF, PNG and JPEG files are accepted.",
        }
    ]
    assert count(seeded, Document) == 0
    assert count(seeded, Batch) == 0
    assert originals(tmp_path) == []


@pytest.mark.parametrize(
    ("filename", "content_type", "data", "media_type"),
    [
        ("notes.txt", "text/plain", pdf_bytes(), "application/pdf"),
        ("photo.jpg", "image/jpeg", pdf_bytes(), "application/pdf"),
        ("scan.pdf", "application/pdf", png_bytes(), "image/png"),
        ("no-extension", "application/octet-stream", jpeg_bytes(), "image/jpeg"),
    ],
)
def test_real_file_with_a_wrong_name_is_accepted_by_content(
    client: TestClient,
    csrf: str,
    seeded: Engine,
    filename: str,
    content_type: str,
    data: bytes,
    media_type: str,
) -> None:
    response = post_files(client, csrf, part(filename, data, content_type))

    assert response.status_code == 201
    with Session(seeded) as session:
        assert session.scalars(select(Document)).one().media_type == media_type


def test_mixed_batch_reports_each_file_and_keeps_the_good_ones(
    client: TestClient, csrf: str, seeded: Engine
) -> None:
    response = post_files(client, csrf, part("good.pdf", pdf_bytes()), part("bad.pdf", b"nonsense"))

    assert response.status_code == 201
    good, bad = response.json()["files"]
    assert good["documentId"]
    assert bad["documentId"] is None
    assert bad["code"] == "unsupported_type"
    assert count(seeded, Document) == 1


@pytest.mark.parametrize(
    ("limits", "data", "code"),
    [
        ({"max_pdf_bytes": 100}, pdf_bytes(), "too_large"),
        ({"max_image_bytes": 20}, png_bytes(), "too_large"),
        ({"max_pdf_pages": 1}, pdf_bytes(pages=2), "too_many_pages"),
        ({"max_image_side": 10}, png_bytes(), "image_too_large"),
        ({"max_image_pixels": 10}, png_bytes(), "image_too_large"),
    ],
)
def test_each_limit_is_refused_with_a_clear_error(
    seeded: Engine, build: BuildApp, limits: dict[str, int], data: bytes, code: str
) -> None:
    with https_client(build(**limits)) as client:
        csrf = sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)

        response = post_files(client, csrf, part("file", data))

    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == code
    assert response.json()["errors"][0]["detail"]
    assert count(seeded, Document) == 0


def test_file_over_both_limits_is_refused_without_being_read(
    seeded: Engine, build: BuildApp
) -> None:
    with https_client(build(max_pdf_bytes=1000, max_image_bytes=1000)) as client:
        csrf = sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)

        response = post_files(client, csrf, part("big.pdf", b"%PDF-" + b"x" * 2000))

    assert response.json()["errors"][0]["code"] == "too_large"


def test_same_file_twice_makes_one_document(
    client: TestClient, csrf: str, seeded: Engine, tmp_path: Path
) -> None:
    data = pdf_bytes()

    first = post_files(client, csrf, part("first.pdf", data))
    second = post_files(client, csrf, part("renamed.pdf", data))

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["batchId"] is None
    assert second.json()["files"][0]["deduplicated"] is True
    assert second.json()["files"][0]["documentId"] == first.json()["files"][0]["documentId"]
    assert count(seeded, Document) == 1
    assert count(seeded, Job) == 1
    assert count(seeded, Batch) == 1
    assert len(originals(tmp_path)) == 1


def test_same_image_twice_is_matched_on_the_uploaded_bytes(
    client: TestClient, csrf: str, seeded: Engine
) -> None:
    data = jpeg_bytes()

    post_files(client, csrf, part("a.jpg", data))
    second = post_files(client, csrf, part("a.jpg", data))

    assert second.status_code == 200
    assert count(seeded, Document) == 1


def test_same_file_twice_in_one_request_makes_one_document(
    client: TestClient, csrf: str, seeded: Engine, tmp_path: Path
) -> None:
    data = pdf_bytes()

    response = post_files(client, csrf, part("a.pdf", data), part("b.pdf", data))

    assert response.status_code == 201
    first, second = response.json()["files"]
    assert first["documentId"] == second["documentId"]
    assert second["deduplicated"] is True
    assert count(seeded, Document) == 1
    assert len(originals(tmp_path)) == 1


def test_concurrent_uploads_of_one_file_make_one_document(
    client: TestClient, csrf: str, seeded: Engine, tmp_path: Path
) -> None:
    data = pdf_bytes()
    barrier = threading.Barrier(8)
    statuses: list[int] = []

    def upload() -> None:
        barrier.wait()
        statuses.append(post_files(client, csrf, part("same.pdf", data)).status_code)

    threads = [threading.Thread(target=upload) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(statuses) == 8
    assert statuses.count(500) == 0
    assert count(seeded, Document) == 1
    assert count(seeded, Job) == 1
    assert len(originals(tmp_path)) == 1


def test_batch_file_cap(seeded: Engine, build: BuildApp) -> None:
    with https_client(build(max_batch_files=2)) as client:
        csrf = sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)

        allowed = post_files(
            client, csrf, part("1.pdf", pdf_bytes(seed=1)), part("2.pdf", pdf_bytes(seed=2))
        )
        refused = post_files(
            client,
            csrf,
            part("3.pdf", pdf_bytes(seed=3)),
            part("4.pdf", pdf_bytes(seed=4)),
            part("5.pdf", pdf_bytes(seed=5)),
        )

    assert allowed.status_code == 201
    assert refused.status_code == 400
    assert refused.headers["content-type"] == "application/problem+json"
    assert count(seeded, Document) == 2


def test_upload_rate_limit_is_per_user(seeded: Engine, build: BuildApp) -> None:
    app = build(upload_rate_limit="2/minute")
    with https_client(app) as client:
        csrf = sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
        statuses = [
            post_files(client, csrf, part("a.pdf", pdf_bytes(seed=number))).status_code
            for number in range(3)
        ]
    with https_client(app) as other_user:
        csrf = sign_in(other_user, ADMIN_EMAIL, ADMIN_PASSWORD)
        other = post_files(other_user, csrf, part("b.pdf", pdf_bytes(seed=9)))

    assert statuses == [201, 201, 429]
    assert other.status_code == 201


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("..\\..\\windows\\system32\\evil.pdf", "evil.pdf"),
        ("/absolute/path.pdf", "path.pdf"),
        ("../", "unnamed"),
    ],
)
def test_file_name_cannot_choose_where_a_file_lands(
    client: TestClient, csrf: str, seeded: Engine, tmp_path: Path, raw: str, shown: str
) -> None:
    response = post_files(client, csrf, part(raw, pdf_bytes()))

    assert response.status_code == 201
    assert response.json()["files"][0]["filename"] == shown
    stored = originals(tmp_path)
    assert len(stored) == 1
    assert uuid.UUID(stored[0].name)
    assert stored[0].parent == tmp_path / "storage" / "originals"
    with Session(seeded) as session:
        document = session.scalars(select(Document)).one()
    assert document.original_filename == shown
    assert shown == "unnamed" or shown not in document.storage_key


def test_stored_image_is_the_clean_copy(client: TestClient, csrf: str, tmp_path: Path) -> None:
    payload = b"%PDF-1.7 hidden payload"

    post_files(client, csrf, part("polyglot.jpg", jpeg_bytes() + payload))

    assert payload not in originals(tmp_path)[0].read_bytes()


def test_body_is_not_read_for_an_anonymous_caller(
    seeded: Engine, build: BuildApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_if_parsed(*_: object, **__: object) -> None:
        pytest.fail("the body was parsed before the access checks")

    monkeypatch.setattr("starlette.requests.Request.form", fail_if_parsed)

    with https_client(build()) as client:
        response = client.post(
            DOCUMENTS, files=[part("a.pdf", pdf_bytes())], headers={"Origin": ORIGIN}
        )

    assert response.status_code == 401
    assert originals(tmp_path) == []


def test_declared_size_over_the_batch_maximum_is_refused_first(
    seeded: Engine, build: BuildApp
) -> None:
    with https_client(build(max_batch_files=1, max_pdf_bytes=1, max_image_bytes=1)) as client:
        csrf = sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)

        response = client.post(
            DOCUMENTS,
            content=b"x" * (2 * 1024 * 1024),
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf, "Content-Type": "multipart/form-data"},
        )

    assert response.status_code == 413


def test_body_without_a_declared_length_is_refused(client: TestClient, csrf: str) -> None:
    def chunks() -> Iterator[bytes]:
        yield b"x"

    response = client.post(
        DOCUMENTS, content=chunks(), headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}
    )

    assert response.status_code == 411


def test_request_without_files_is_refused(client: TestClient, csrf: str) -> None:
    response = client.post(
        DOCUMENTS,
        data={"not_files": "x"},
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
    )

    assert response.status_code == 422


def upload_several(client: TestClient, csrf: str, clock: FakeClock, names: list[str]) -> list[str]:
    ids: list[str] = []
    for number, name in enumerate(names):
        clock.advance(timedelta(seconds=1))
        response = post_files(client, csrf, part(name, pdf_bytes(seed=number)))
        ids.append(response.json()["files"][0]["documentId"])
    return ids


def walk(client: TestClient, query: str) -> list[list[str]]:
    pages: list[list[str]] = []
    cursor = None
    while True:
        params = f"{query}&cursor={cursor}" if cursor else query
        response = client.get(f"{DOCUMENTS}?{params}")
        assert response.status_code == 200
        pages.append([item["id"] for item in response.json()["items"]])
        cursor = response.json()["nextCursor"]
        if cursor is None:
            return pages


def test_paging_visits_every_document_once_newest_first(
    client: TestClient, csrf: str, clock: FakeClock
) -> None:
    ids = upload_several(client, csrf, clock, ["a", "b", "c", "d", "e"])

    pages = walk(client, "limit=2")

    assert [len(page) for page in pages] == [2, 2, 1]
    assert [item for page in pages for item in page] == list(reversed(ids))


def test_paging_is_exact_when_the_last_page_is_full(
    client: TestClient, csrf: str, clock: FakeClock
) -> None:
    upload_several(client, csrf, clock, ["a", "b", "c", "d"])

    assert [len(page) for page in walk(client, "limit=2")] == [2, 2]


def test_rows_with_the_same_sort_value_are_not_lost(
    client: TestClient, csrf: str, clock: FakeClock
) -> None:
    ids = [
        post_files(client, csrf, part("same", pdf_bytes(seed=number))).json()["files"][0][
            "documentId"
        ]
        for number in range(5)
    ]

    pages = walk(client, "limit=2&sort=filename")

    assert sorted(item for page in pages for item in page) == sorted(ids)


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        ("received_at", ["b", "a", "c"]),
        ("-received_at", ["c", "a", "b"]),
        ("filename", ["a", "b", "c"]),
        ("-filename", ["c", "b", "a"]),
    ],
)
def test_each_allowed_sort(
    client: TestClient, csrf: str, clock: FakeClock, sort: str, expected: list[str]
) -> None:
    upload_several(client, csrf, clock, ["b", "a", "c"])

    pages = client.get(f"{DOCUMENTS}?sort={sort}&limit=2")
    next_page = client.get(f"{DOCUMENTS}?sort={sort}&limit=2&cursor={pages.json()['nextCursor']}")

    names = [item["filename"] for item in pages.json()["items"] + next_page.json()["items"]]
    assert names == expected


@pytest.mark.parametrize(
    "sort", ["sha256", "storage_key", "id; DROP TABLE documents", "received_at desc"]
)
def test_sort_outside_the_allow_list_is_refused(
    client: TestClient, csrf: str, seeded: Engine, sort: str
) -> None:
    post_files(client, csrf, part("a.pdf", pdf_bytes()))

    response = client.get(DOCUMENTS, params={"sort": sort})

    assert response.status_code == 422
    assert count(seeded, Document) == 1


def test_status_filter(client: TestClient, csrf: str, seeded: Engine, clock: FakeClock) -> None:
    ids = upload_several(client, csrf, clock, ["a", "b"])
    with Session(seeded) as session, session.begin():
        session.get_one(Document, uuid.UUID(ids[0])).status = DocumentStatus.FAILED

    response = client.get(f"{DOCUMENTS}?status=failed")

    assert [item["id"] for item in response.json()["items"]] == [ids[0]]
    assert client.get(f"{DOCUMENTS}?status=nonsense").status_code == 422


@pytest.mark.parametrize("limit", [0, 101, -1])
def test_limit_is_bounded(client: TestClient, csrf: str, limit: int) -> None:
    assert client.get(f"{DOCUMENTS}?limit={limit}").status_code == 422


def cursor_of(*values: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(list(values)).encode()).decode()


@pytest.mark.parametrize(
    "cursor",
    [
        "not base64!",
        base64.urlsafe_b64encode(b"not json").decode(),
        cursor_of("-received_at"),
        cursor_of("-received_at", "not a date", str(uuid.uuid4())),
        cursor_of("-received_at", "2026-01-01T00:00:00+00:00", "not a uuid"),
        cursor_of("-received_at", 5, str(uuid.uuid4())),
        cursor_of("filename", "a", str(uuid.uuid4())),
        cursor_of("received_at", "2026-01-01T00:00:00+00:00", str(uuid.uuid4())),
    ],
    ids=["base64", "json", "short", "date", "uuid", "type", "other-sort", "other-direction"],
)
def test_bad_cursor_is_refused(client: TestClient, csrf: str, cursor: str) -> None:
    response = client.get(DOCUMENTS, params={"cursor": cursor})

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"


def test_empty_list(client: TestClient, csrf: str) -> None:
    assert client.get(DOCUMENTS).json() == {"items": [], "nextCursor": None}


def test_detail(client: TestClient, csrf: str) -> None:
    document_id = post_files(client, csrf, part("a.pdf", pdf_bytes())).json()["files"][0][
        "documentId"
    ]

    body = client.get(f"{DOCUMENTS}/{document_id}").json()

    assert body["filename"] == "a.pdf"
    assert body["status"] == "queued"
    assert body["pageCount"] == 1
    assert body["statusReasons"] == []
    assert "storageKey" not in body
    assert "storage_key" not in body


def test_missing_document_and_page_are_404(client: TestClient, csrf: str) -> None:
    missing = uuid.uuid4()

    assert client.get(f"{DOCUMENTS}/{missing}").status_code == 404
    assert client.get(f"{DOCUMENTS}/{missing}/pages/1").status_code == 404
    assert client.get(f"{DOCUMENTS}/{missing}/pages/0").status_code == 422
    assert client.get(f"{DOCUMENTS}/not-a-uuid").status_code == 422
