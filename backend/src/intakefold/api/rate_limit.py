import math
import time
from collections.abc import Sequence
from ipaddress import IPv4Network, IPv6Network, ip_address

from fastapi import HTTPException, Request
from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

from intakefold.api.access import CurrentUser


class RateLimiter:
    """In memory, per process: limits reset on restart, and one API process is all we run."""

    def __init__(self, limit: str) -> None:
        self._item = parse(limit)
        self._limiter = MovingWindowRateLimiter(MemoryStorage())

    def retry_after(self, key: str) -> int | None:
        """Counts one attempt. Returns seconds to wait if it is over the limit."""
        if self._limiter.hit(self._item, key):
            return None
        reset_time = self._limiter.get_window_stats(self._item, key).reset_time
        return max(1, math.ceil(reset_time - time.time()))


def client_ip(request: Request, trusted: Sequence[IPv4Network | IPv6Network]) -> str:
    """The peer, unless the peer is a trusted proxy that states who it forwarded for."""
    peer = request.client.host if request.client else "unknown"
    if not _is_trusted(peer, trusted):
        return peer
    hops = ",".join(request.headers.getlist("x-forwarded-for")).split(",")
    # Right to left: entries left of the last trusted hop are whatever the client sent.
    for hop in map(str.strip, reversed(hops)):
        try:
            ip_address(hop)
        except ValueError:
            return peer
        if not _is_trusted(hop, trusted):
            return hop
    return peer


def _is_trusted(address: str, trusted: Sequence[IPv4Network | IPv6Network]) -> bool:
    try:
        parsed = ip_address(address)
    except ValueError:
        return False
    return any(parsed in network for network in trusted)


def limit_sign_in(request: Request) -> None:
    limiter: RateLimiter = request.app.state.sign_in_limiter
    trusted: Sequence[IPv4Network | IPv6Network] = request.app.state.settings.trusted_proxies
    enforce(limiter, client_ip(request, trusted), "Too many sign-in attempts. Try again later.")


def limit_upload(request: Request, principal: CurrentUser) -> None:
    limiter: RateLimiter = request.app.state.upload_limiter
    enforce(limiter, str(principal.user_id), "Too many uploads. Try again later.")


def enforce(limiter: RateLimiter, key: str, detail: str) -> None:
    retry_after = limiter.retry_after(key)
    if retry_after is not None:
        raise HTTPException(
            status_code=429, detail=detail, headers={"Retry-After": str(retry_after)}
        )
