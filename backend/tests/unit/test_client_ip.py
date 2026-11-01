from ipaddress import ip_network

import pytest
from fastapi import Request

from intakefold.api.rate_limit import client_ip

PROXIES = (ip_network("10.0.0.0/8"),)


def request_from(peer: str, forwarded: str | None = None) -> Request:
    headers = [] if forwarded is None else [(b"x-forwarded-for", forwarded.encode())]
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


def test_untrusted_peer_cannot_state_a_client_ip() -> None:
    assert client_ip(request_from("203.0.113.9", "198.51.100.1"), PROXIES) == "203.0.113.9"


def test_no_proxies_configured_means_the_header_is_ignored() -> None:
    assert client_ip(request_from("10.1.2.3", "198.51.100.1"), ()) == "10.1.2.3"


def test_trusted_proxy_supplies_the_client_ip() -> None:
    assert client_ip(request_from("10.1.2.3", "198.51.100.1"), PROXIES) == "198.51.100.1"


def test_entries_the_client_added_on_the_left_are_ignored() -> None:
    request = request_from("10.1.2.3", "192.0.2.77, 198.51.100.1")

    assert client_ip(request, PROXIES) == "198.51.100.1"


def test_a_chain_of_proxies_is_walked_from_the_right() -> None:
    request = request_from("10.1.2.3", "198.51.100.1, 10.9.9.9")

    assert client_ip(request, PROXIES) == "198.51.100.1"


@pytest.mark.parametrize("forwarded", [None, "", "not-an-address", "10.9.9.9"])
def test_falls_back_to_the_peer_without_a_usable_address(forwarded: str | None) -> None:
    assert client_ip(request_from("10.1.2.3", forwarded), PROXIES) == "10.1.2.3"


def test_missing_peer_does_not_crash() -> None:
    assert client_ip(Request({"type": "http", "client": None, "headers": []}), PROXIES) == "unknown"
