"""Webhook signatures: `t=<unix seconds>,v1=<hex HMAC-SHA-256 of "t.body">`."""

import hashlib
import hmac

SIGNATURE_HEADER = "Intakefold-Signature"
EVENT_ID_HEADER = "Intakefold-Event-Id"
DEFAULT_TOLERANCE_SECONDS = 300


def signature(secret: str, timestamp: int, body: bytes) -> str:
    message = str(timestamp).encode() + b"." + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def signature_header(secret: str, timestamp: int, body: bytes) -> str:
    return f"t={timestamp},v1={signature(secret, timestamp, body)}"


def parse_header(header: str) -> tuple[int, list[str]] | None:
    timestamp: int | None = None
    signatures: list[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t" and value.isdecimal():
            timestamp = int(value)
        elif key == "v1" and value:
            signatures.append(value)
    if timestamp is None or not signatures:
        return None
    return timestamp, signatures


def verify(
    secret: str,
    header: str,
    body: bytes,
    now: int,
    tolerance: int = DEFAULT_TOLERANCE_SECONDS,
) -> bool:
    parsed = parse_header(header)
    if parsed is None:
        return False
    timestamp, candidates = parsed
    # Too old is a replay; too far ahead is a clock that cannot be trusted either.
    if abs(now - timestamp) > tolerance:
        return False
    expected = signature(secret, timestamp, body)
    # compare_digest takes the same time wherever the strings differ, so it leaks nothing.
    return any(hmac.compare_digest(expected, candidate) for candidate in candidates)
