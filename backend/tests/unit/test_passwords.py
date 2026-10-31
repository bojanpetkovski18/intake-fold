from intakefold.identity.passwords import hash_password, verify_password
from intakefold.identity.sessions import csrf_token_for, hash_token


def test_hash_is_argon2id_and_verifies() -> None:
    stored = hash_password("correct horse")

    assert stored.startswith("$argon2id$")
    assert "correct horse" not in stored
    assert verify_password(stored, "correct horse")
    assert not verify_password(stored, "wrong horse")


def test_same_password_hashes_differently() -> None:
    assert hash_password("correct horse") != hash_password("correct horse")


def test_a_malformed_stored_hash_never_verifies() -> None:
    assert not verify_password("!", "anything")


def test_csrf_token_is_stable_and_differs_from_the_session_token() -> None:
    assert csrf_token_for("token-a") == csrf_token_for("token-a")
    assert csrf_token_for("token-a") != csrf_token_for("token-b")
    assert csrf_token_for("token-a") != hash_token("token-a")
