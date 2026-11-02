import csv
import io
import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from intakefold.delivery import signing
from intakefold.delivery.export import number, safe_text
from intakefold.delivery.signing import (
    EVENT_ID_HEADER,
    SIGNATURE_HEADER,
    signature,
    signature_header,
    verify,
)
from intakefold.settings import ConfigurationError, load_settings
from intakefold_sink.app import build_sink

SECRET = "whsec_test_secret_for_known_answer"  # noqa: S105 - fictional test secret
NOW = 1767225600
BODY = b'{"a":1}'


def test_signature_matches_an_independent_implementation() -> None:
    # Computed with: printf '%s' '1767225600.{"a":1}' | openssl dgst -sha256 -hmac '<SECRET>'
    expected = "2e17cf2c11d9d9c53933e376132d9b796aeca87e47d454ae1bb0566263126529"

    assert signature(SECRET, NOW, BODY) == expected
    assert signature_header(SECRET, NOW, BODY) == f"t={NOW},v1={expected}"


def test_a_valid_signature_verifies() -> None:
    assert verify(SECRET, signature_header(SECRET, NOW, BODY), BODY, NOW)


def test_a_tampered_body_fails() -> None:
    header = signature_header(SECRET, NOW, BODY)

    assert not verify(SECRET, header, b'{"a":2}', NOW)


def test_another_secret_fails() -> None:
    header = signature_header("another-secret-of-enough-length-0000", NOW, BODY)

    assert not verify(SECRET, header, BODY, NOW)


@pytest.mark.parametrize(("age", "valid"), [(300, True), (301, False), (-300, True), (-301, False)])
def test_timestamp_window(age: int, valid: bool) -> None:
    header = signature_header(SECRET, NOW - age, BODY)

    assert verify(SECRET, header, BODY, NOW) is valid


def test_a_moved_timestamp_breaks_the_signature() -> None:
    old = signature_header(SECRET, NOW - 1000, BODY)
    forged = old.replace(f"t={NOW - 1000}", f"t={NOW}")

    assert not verify(SECRET, forged, BODY, NOW)


@pytest.mark.parametrize(
    "header",
    ["", "garbage", f"t={NOW}", "v1=abc", f"t=soon,v1={'0' * 64}", f"t={NOW},v1="],
)
def test_malformed_headers_fail(header: str) -> None:
    assert not verify(SECRET, header, BODY, NOW)


def test_any_listed_signature_may_match_during_secret_rotation() -> None:
    good = signature(SECRET, NOW, BODY)

    assert verify(SECRET, f"t={NOW},v1={'0' * 64},v1={good}", BODY, NOW)


def test_comparison_is_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def spy(left: str, right: str) -> bool:
        calls.append((left, right))
        return left == right

    monkeypatch.setattr(signing.hmac, "compare_digest", spy)

    verify(SECRET, signature_header(SECRET, NOW, BODY), BODY, NOW)

    assert calls


# Written out from SPEC section 9, not taken from the code, so the test can disagree with it.
@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_each_formula_prefix_is_neutralized(prefix: str) -> None:
    assert safe_text(f"{prefix}HYPERLINK(1)") == f"'{prefix}HYPERLINK(1)"


def test_ordinary_text_is_untouched() -> None:
    assert safe_text("Tarnwell Freight") == "Tarnwell Freight"
    assert safe_text(None) == ""


def test_negative_money_stays_a_number() -> None:
    assert number(Decimal("-12.5000")) == "-12.50"
    assert number(Decimal("1234.5678")) == "1234.5678"
    assert number(None) == ""


def test_commas_quotes_and_newlines_survive_a_round_trip() -> None:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    awkward = 'Line one, "quoted"\nline two'
    writer.writerow([safe_text(awkward), number(Decimal("-5.00"))])

    rows = list(csv.reader(io.StringIO(buffer.getvalue())))

    assert rows == [[awkward, "-5.00"]]


def sink_client(fail_first: int = 0) -> TestClient:
    return TestClient(build_sink(SECRET, fail_first, now=lambda: NOW))


def post(client: TestClient, event_id: str, body: bytes = BODY, header: str | None = None):
    return client.post(
        "/webhook",
        content=body,
        headers={
            SIGNATURE_HEADER: header or signature_header(SECRET, NOW, body),
            EVENT_ID_HEADER: event_id,
            "Content-Type": "application/json",
        },
    )


def test_sink_accepts_a_signed_event_and_shows_it() -> None:
    client = sink_client()

    response = post(client, "e1")

    assert response.status_code == 200
    assert response.json() == {"duplicate": False}
    assert client.get("/events").json() == [{"event_id": "e1", "payload": {"a": 1}}]


def test_sink_processes_a_repeat_event_once() -> None:
    client = sink_client()

    post(client, "e1")
    repeat = post(client, "e1")

    assert repeat.status_code == 200
    assert repeat.json() == {"duplicate": True}
    assert len(client.get("/events").json()) == 1


def test_sink_refuses_a_tampered_body() -> None:
    client = sink_client()
    header = signature_header(SECRET, NOW, BODY)

    response = post(client, "e1", body=b'{"a":999}', header=header)

    assert response.status_code == 401
    assert client.get("/events").json() == []


def test_sink_refuses_an_old_timestamp() -> None:
    client = sink_client()

    response = post(client, "e1", header=signature_header(SECRET, NOW - 301, BODY))

    assert response.status_code == 401


def test_sink_refuses_an_event_without_an_id() -> None:
    assert post(sink_client(), "").status_code == 400


def test_sink_can_fail_the_first_attempts_of_each_event() -> None:
    client = sink_client(fail_first=2)

    statuses = [post(client, "e1").status_code for _ in range(3)]

    assert statuses == [503, 503, 200]
    assert post(client, "e2").status_code == 503


def test_sink_page_escapes_what_it_received() -> None:
    client = sink_client()
    body = json.dumps({"vendor": "<script>alert(1)</script>"}).encode()

    post(client, "e1", body=body)
    page = client.get("/")

    assert "<script>alert(1)" not in page.text
    assert "&lt;script&gt;" in page.text
    assert "default-src 'none'" in page.headers["content-security-policy"]


def test_sink_needs_a_long_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    from intakefold_sink.app import create_app

    monkeypatch.setenv("SINK_SECRET", "short")

    with pytest.raises(SystemExit, match="SINK_SECRET"):
        create_app()


def targets(value: object) -> str:
    return json.dumps(value)


def test_webhook_targets_are_read_from_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@host/db")
    monkeypatch.setenv(
        "WEBHOOK_TARGETS",
        targets([{"name": "sink", "url": "http://127.0.0.1:8190/webhook", "secret": SECRET}]),
    )

    settings = load_settings()

    assert settings.webhook_targets[0].name == "sink"
    assert SECRET not in repr(settings)


@pytest.mark.parametrize(
    "value",
    [
        [{"name": "sink", "url": "ftp://example.com/x", "secret": SECRET}],
        [{"name": "sink", "url": "not a url", "secret": SECRET}],
        [{"name": "sink", "url": "http://127.0.0.1/x", "secret": "short"}],
        [{"name": "Bad Name", "url": "http://127.0.0.1/x", "secret": SECRET}],
        [
            {"name": "a", "url": "http://127.0.0.1/x", "secret": SECRET},
            {"name": "a", "url": "http://127.0.0.1/y", "secret": SECRET},
        ],
        [{"name": "a", "url": "http://127.0.0.1/x", "secret": SECRET, "extra": 1}],
    ],
)
def test_bad_targets_stop_startup_without_echoing_the_secret(
    monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@host/db")
    monkeypatch.setenv("WEBHOOK_TARGETS", targets(value))

    with pytest.raises(ConfigurationError, match="WEBHOOK_TARGETS") as caught:
        load_settings()

    assert SECRET not in str(caught.value)
