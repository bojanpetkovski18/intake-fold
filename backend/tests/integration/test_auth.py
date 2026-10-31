import time
from collections.abc import Iterator
from datetime import timedelta

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
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session
from support import FakeClock

from intakefold.api.access import SESSION_COOKIE
from intakefold.db.models import Session as UserSession

pytestmark = pytest.mark.integration

LOGIN = "/api/auth/login"
LOGOUT = "/api/auth/logout"
ME = "/api/auth/me"
ORIGIN_HEADER = {"Origin": ORIGIN}


def session_count(engine: Engine) -> int:
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(UserSession)) or 0


def login(client: TestClient, email: str, password: str, **headers: str):
    return client.post(
        LOGIN, json={"email": email, "password": password}, headers=ORIGIN_HEADER | headers
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def client(seeded: Engine, build: BuildApp, clock: FakeClock) -> Iterator[TestClient]:
    with https_client(build(clock)) as client:
        yield client


def test_correct_password_signs_in(client: TestClient) -> None:
    response = login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == REVIEWER_EMAIL
    assert body["user"]["displayName"] == "Riley Reviewer"
    assert body["user"]["role"] == "reviewer"
    assert body["csrfToken"]
    assert "password" not in response.text


def test_session_cookie_is_locked_down(client: TestClient) -> None:
    cookie = login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD).headers["set-cookie"]

    attributes = {part.strip().lower() for part in cookie.split(";")}
    assert {"httponly", "secure", "samesite=strict", "path=/api"} <= attributes
    assert "max-age=43200" in attributes


def test_insecure_cookie_needs_the_explicit_switch(seeded: Engine, build: BuildApp) -> None:
    with https_client(build(allow_insecure_cookies=True)) as client:
        cookie = login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD).headers["set-cookie"]

    assert "secure" not in cookie.lower()
    assert "httponly" in cookie.lower()


def test_me_returns_the_user_and_the_same_csrf_token(client: TestClient) -> None:
    csrf_token = sign_in(client, ADMIN_EMAIL, ADMIN_PASSWORD)

    response = client.get(ME)

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "admin"
    assert response.json()["csrfToken"] == csrf_token


def test_email_ignores_case_and_outer_spaces(client: TestClient) -> None:
    response = login(client, "  Reviewer@Example.COM ", REVIEWER_PASSWORD)

    assert response.status_code == 200


def test_tokens_are_stored_only_as_hashes(client: TestClient, seeded: Engine) -> None:
    csrf_token = sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    token = client.cookies[SESSION_COOKIE]

    with Session(seeded) as session:
        row = session.scalars(select(UserSession)).one()

    assert token not in (row.token_hash, row.csrf_token_hash)
    assert csrf_token not in (row.token_hash, row.csrf_token_hash)
    assert len(row.token_hash) == 64


def test_wrong_password_and_unknown_email_look_the_same(client: TestClient, seeded: Engine) -> None:
    wrong = login(client, REVIEWER_EMAIL, "not-the-password")
    unknown = login(client, "nobody@example.com", "not-the-password")

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]
    assert "set-cookie" not in wrong.headers
    assert session_count(seeded) == 0


def test_unknown_email_still_spends_hashing_time(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr("intakefold.identity.sessions.spend_verification_time", calls.append)

    login(client, "nobody@example.com", "not-the-password")

    assert calls == ["not-the-password"]


def test_session_ends_exactly_at_expiry(client: TestClient, clock: FakeClock) -> None:
    sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)

    clock.advance(timedelta(hours=12) - timedelta(seconds=1))
    assert client.get(ME).status_code == 200

    clock.advance(timedelta(seconds=1))
    assert client.get(ME).status_code == 401


def test_next_sign_in_removes_expired_sessions(
    client: TestClient, seeded: Engine, clock: FakeClock
) -> None:
    sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    clock.advance(timedelta(hours=13))

    sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)

    assert session_count(seeded) == 1


def test_logout_ends_the_session_on_the_server(client: TestClient, seeded: Engine) -> None:
    csrf_token = sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    token = client.cookies[SESSION_COOKIE]

    response = client.post(LOGOUT, headers=ORIGIN_HEADER | {"X-CSRF-Token": csrf_token})

    assert response.status_code == 204
    assert 'intakefold_session=""' in response.headers["set-cookie"]
    assert session_count(seeded) == 0
    # A copy of the cookie kept by anyone is now worthless.
    client.cookies.set(SESSION_COOKIE, token, domain="testserver", path="/api")
    assert client.get(ME).status_code == 401


def test_logout_leaves_other_sessions_alone(
    client: TestClient, build: BuildApp, clock: FakeClock
) -> None:
    csrf_token = sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    with https_client(build(clock)) as other_device:
        sign_in(other_device, REVIEWER_EMAIL, REVIEWER_PASSWORD)

        response = client.post(LOGOUT, headers=ORIGIN_HEADER | {"X-CSRF-Token": csrf_token})

        assert response.status_code == 204
        assert other_device.get(ME).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-CSRF-Token": "wrong"},
    ],
    ids=["missing", "wrong"],
)
def test_logout_needs_a_valid_csrf_token(
    client: TestClient, seeded: Engine, headers: dict[str, str]
) -> None:
    sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)

    response = client.post(LOGOUT, headers=ORIGIN_HEADER | headers)

    assert response.status_code == 403
    assert session_count(seeded) == 1


def test_csrf_token_of_another_session_is_refused(
    client: TestClient, build: BuildApp, clock: FakeClock
) -> None:
    sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    with https_client(build(clock)) as other:
        other_token = sign_in(other, ADMIN_EMAIL, ADMIN_PASSWORD)

    response = client.post(LOGOUT, headers=ORIGIN_HEADER | {"X-CSRF-Token": other_token})

    assert response.status_code == 403


@pytest.mark.parametrize(
    "headers",
    [{}, {"Origin": "https://evil.example.com"}, {"Origin": "null"}],
    ids=["missing", "other-site", "null"],
)
def test_login_refuses_a_bad_origin(
    client: TestClient, seeded: Engine, headers: dict[str, str]
) -> None:
    response = client.post(
        LOGIN, json={"email": REVIEWER_EMAIL, "password": REVIEWER_PASSWORD}, headers=headers
    )

    assert response.status_code == 403
    assert response.headers["content-type"] == "application/problem+json"
    assert session_count(seeded) == 0


def test_overlong_password_is_refused_and_not_echoed(client: TestClient) -> None:
    password = "s3cret-" * 40

    response = login(client, REVIEWER_EMAIL, password)

    assert response.status_code == 422
    assert "s3cret" not in response.text


def test_sign_in_rate_limit_counts_every_attempt(seeded: Engine, build: BuildApp) -> None:
    with https_client(build(sign_in_rate_limit="2/minute")) as client:
        statuses = [
            login(client, REVIEWER_EMAIL, "not-the-password").status_code,
            login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD).status_code,
        ]
        limited = login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)

    assert statuses == [401, 200]
    assert limited.status_code == 429
    assert limited.headers["content-type"] == "application/problem+json"
    assert 1 <= int(limited.headers["retry-after"]) <= 60


def test_rate_limit_frees_up_after_the_window(seeded: Engine, build: BuildApp) -> None:
    with https_client(build(sign_in_rate_limit="1/second")) as client:
        assert login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD).status_code == 200
        assert login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD).status_code == 429

        deadline = time.monotonic() + 5
        status = 429
        while status == 429 and time.monotonic() < deadline:
            status = login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD).status_code

    assert status == 200


def test_rate_limit_cannot_be_dodged_by_forging_a_forwarded_header(
    seeded: Engine, build: BuildApp
) -> None:
    with https_client(build(sign_in_rate_limit="1/minute")) as client:
        first = client.post(
            LOGIN,
            json={"email": REVIEWER_EMAIL, "password": "not-the-password"},
            headers=ORIGIN_HEADER | {"X-Forwarded-For": "198.51.100.1"},
        )
        second = client.post(
            LOGIN,
            json={"email": REVIEWER_EMAIL, "password": "not-the-password"},
            headers=ORIGIN_HEADER | {"X-Forwarded-For": "198.51.100.2"},
        )

    assert first.status_code == 401
    assert second.status_code == 429


def test_trusted_proxy_keeps_clients_in_separate_buckets(seeded: Engine, build: BuildApp) -> None:
    app = build(sign_in_rate_limit="1/minute", trusted_proxies="10.0.0.0/8")
    with https_client(app, client=("10.1.2.3", 50000)) as client:
        for address, expected in [
            ("198.51.100.1", 401),
            ("198.51.100.1", 429),
            ("198.51.100.2", 401),
        ]:
            response = client.post(
                LOGIN,
                json={"email": REVIEWER_EMAIL, "password": "not-the-password"},
                headers=ORIGIN_HEADER | {"X-Forwarded-For": address},
            )
            assert response.status_code == expected


def test_passwords_and_tokens_never_reach_the_logs(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    login(client, REVIEWER_EMAIL, "wrong-password-value")
    login(client, "nobody@example.com", "another-password-value")
    csrf_token = sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    token = client.cookies[SESSION_COOKIE]
    client.get(ME)
    client.post(LOGOUT, headers=ORIGIN_HEADER | {"X-CSRF-Token": csrf_token})

    output = capsys.readouterr().out

    assert "sign_in_succeeded" in output
    assert "sign_in_failed" in output
    for secret in (
        "wrong-password-value",
        "another-password-value",
        REVIEWER_PASSWORD,
        token,
        csrf_token,
    ):
        assert secret not in output
