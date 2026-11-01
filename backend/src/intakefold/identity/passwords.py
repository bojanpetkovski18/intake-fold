import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()
_decoy_hash = _hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except VerificationError, InvalidHashError:
        return False


def spend_verification_time(password: str) -> None:
    """Costs what a real check costs, so timing does not reveal which emails exist."""
    verify_password(_decoy_hash, password)
