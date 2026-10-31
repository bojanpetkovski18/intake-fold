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
