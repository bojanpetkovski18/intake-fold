import pytest

from intakefold.settings import ConfigurationError, load_settings


def test_missing_database_url_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        load_settings()


def test_error_message_does_not_echo_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:hunter2@host/db")
    monkeypatch.setenv("ENVIRONMENT", "secret-looking-value")

    with pytest.raises(ConfigurationError) as caught:
        load_settings()

    assert "ENVIRONMENT" in str(caught.value)
    assert "secret-looking-value" not in str(caught.value)
    assert "hunter2" not in str(caught.value)


def test_database_url_is_hidden_from_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:hunter2@host/db")

    assert "hunter2" not in repr(load_settings())


def test_lists_are_read_from_comma_separated_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:hunter2@host/db")
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://a.example, http://b.example")
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.0/8,fd00::/8")

    settings = load_settings()

    assert settings.allowed_origins == ("http://a.example", "http://b.example")
    assert [str(network) for network in settings.trusted_proxies] == ["10.0.0.0/8", "fd00::/8"]


def test_secure_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:hunter2@host/db")
    monkeypatch.delenv("ALLOW_INSECURE_COOKIES", raising=False)
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)

    settings = load_settings()

    assert settings.allow_insecure_cookies is False
    assert settings.trusted_proxies == ()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TRUSTED_PROXIES", "not-a-network"),
        ("SIGN_IN_RATE_LIMIT", "lots"),
        ("DEMO_ADMIN_PASSWORD", "short"),
        ("SESSION_TTL_HOURS", "0"),
    ],
)
def test_invalid_values_stop_startup_without_echoing_them(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:hunter2@host/db")
    monkeypatch.setenv(name, value)

    with pytest.raises(ConfigurationError) as caught:
        load_settings()

    assert name in str(caught.value)
    assert value not in str(caught.value)


def test_demo_passwords_are_hidden_from_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:hunter2@host/db")
    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", "fictional-admin-password")

    assert "fictional-admin-password" not in repr(load_settings())
