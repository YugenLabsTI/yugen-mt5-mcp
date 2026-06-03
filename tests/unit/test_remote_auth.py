"""Unit tests for resolve_client_ip and trust_proxy_headers_for_bind (T-10, T-11)."""

from __future__ import annotations

from starlette.requests import Request

from yugen_mt5_mcp.remote import resolve_client_ip, trust_proxy_headers_for_bind

# ---------------------------------------------------------------------------
# T-10: resolve_client_ip
# ---------------------------------------------------------------------------


def _make_request(
    *,
    xff: str | None = None,
    client_host: str | None = "127.0.0.1",
    client_port: int = 12345,
) -> Request:
    """Build a minimal Starlette Request scope for unit tests."""
    headers: list[tuple[bytes, bytes]] = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))

    client = (client_host, client_port) if client_host is not None else None
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": headers,
        "client": client,
    }
    return Request(scope)


class TestResolveClientIp:
    def test_trust_proxy_xff_single_hop_returns_xff_ip(self) -> None:
        request = _make_request(xff="203.0.113.55", client_host="127.0.0.1")
        result = resolve_client_ip(request, trust_proxy_headers=True)
        assert result == "203.0.113.55"

    def test_trust_proxy_xff_multi_hop_returns_leftmost(self) -> None:
        request = _make_request(xff="10.0.0.5, 172.16.0.1", client_host="127.0.0.1")
        result = resolve_client_ip(request, trust_proxy_headers=True)
        assert result == "10.0.0.5"

    def test_no_trust_proxy_xff_ignored_returns_socket_peer(self) -> None:
        request = _make_request(xff="203.0.113.55", client_host="1.2.3.4")
        result = resolve_client_ip(request, trust_proxy_headers=False)
        assert result == "1.2.3.4"

    def test_trust_proxy_no_xff_returns_socket_peer(self) -> None:
        request = _make_request(xff=None, client_host="10.0.0.2")
        result = resolve_client_ip(request, trust_proxy_headers=True)
        assert result == "10.0.0.2"

    def test_none_client_no_xff_returns_empty_sentinel(self) -> None:
        request = _make_request(xff=None, client_host=None)
        result = resolve_client_ip(request, trust_proxy_headers=False)
        # Sentinel that fails allowlist — empty string or equivalent falsy value
        assert result == ""


# ---------------------------------------------------------------------------
# T-11: trust_proxy_headers_for_bind
# ---------------------------------------------------------------------------


class TestTrustProxyHeadersForBind:
    def test_loopback_v4_returns_true(self) -> None:
        assert trust_proxy_headers_for_bind("127.0.0.1") is True

    def test_loopback_v6_returns_true(self) -> None:
        assert trust_proxy_headers_for_bind("::1") is True

    def test_private_rfc1918_class_c_returns_true(self) -> None:
        assert trust_proxy_headers_for_bind("192.168.1.1") is True

    def test_private_rfc1918_class_a_returns_true(self) -> None:
        assert trust_proxy_headers_for_bind("10.0.0.1") is True

    def test_private_rfc1918_172_returns_true(self) -> None:
        assert trust_proxy_headers_for_bind("172.16.5.5") is True

    def test_public_google_dns_returns_false(self) -> None:
        assert trust_proxy_headers_for_bind("8.8.8.8") is False

    def test_unspecified_0_0_0_0_returns_false(self) -> None:
        assert trust_proxy_headers_for_bind("0.0.0.0") is False

    def test_documentation_range_returns_false(self) -> None:
        # 203.0.113.x is TEST-NET-3 (RFC 5737) — not RFC 1918, so public tier
        assert trust_proxy_headers_for_bind("203.0.113.1") is False
