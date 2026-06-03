"""T-12: ASGI integration tests for BearerIPAuthMiddleware (S-AUTH-01..S-AUTH-10).

Uses httpx.AsyncClient + httpx.ASGITransport against build_http_app wrapping
a stub ASGI echo app to validate auth, IP resolution, and audit behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from yugen_mt5_mcp.audit import REDACTED, AuditStore
from yugen_mt5_mcp.config import RemoteTransportConfig
from yugen_mt5_mcp.remote import BearerIPAuthMiddleware, trust_proxy_headers_for_bind
from yugen_mt5_mcp.security import RemoteSecurityManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _echo_app(scope: Any, receive: Any, send: Any) -> None:
    """Minimal ASGI echo app — returns 200 with a JSON body."""
    assert scope["type"] == "http"
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": b'{"ok": true}'})


def _make_remote_config(
    *,
    host: str = "127.0.0.1",
    token: str = "tok",
    allowlist: tuple[str, ...] = ("10.0.0.0/8",),
    stateless_http: bool = False,
    allow_insecure: bool = False,
    tls_terminated: bool = False,
) -> RemoteTransportConfig:
    return RemoteTransportConfig(
        enabled=True,
        host=host,
        port=8765,
        bearer_token=token,
        allowlist=allowlist,
        allow_insecure=allow_insecure,
        tls_terminated=tls_terminated,
        stateless_http=stateless_http,
    )


def _make_manager(
    config: RemoteTransportConfig,
    audit_store: AuditStore,
) -> RemoteSecurityManager:
    return RemoteSecurityManager(config, audit_store=audit_store)


def _make_asgi_app(
    *,
    config: RemoteTransportConfig,
    audit_store: AuditStore,
    inner: Any = _echo_app,
) -> Any:
    """Wrap the inner ASGI app directly in BearerIPAuthMiddleware (no FastMCP)."""
    manager = _make_manager(config, audit_store)
    trust = trust_proxy_headers_for_bind(config.host)
    return BearerIPAuthMiddleware(
        inner,
        security_manager=manager,
        trust_proxy_headers=trust,
    )


# ---------------------------------------------------------------------------
# S-AUTH-01 — valid token + allowed IP → 200 pass-through; audit allowed
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_auth01_valid_token_allowed_ip_passes_through(tmp_path: Path) -> None:
    audit = AuditStore(tmp_path / "audit.sqlite3")
    config = _make_remote_config(host="127.0.0.1", allowlist=("10.0.0.0/8",))
    app = _make_asgi_app(config=config, audit_store=audit)

    transport = httpx.ASGITransport(app=app, client=("10.0.0.5", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/", headers={"Authorization": "Bearer tok"})

    assert response.status_code == 200
    rows = audit.fetch_all()
    assert len(rows) == 1
    assert rows[0]["decision"] == "allowed"


# ---------------------------------------------------------------------------
# S-AUTH-02 — missing Authorization → 401; audit blocked
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_auth02_missing_token_returns_401(tmp_path: Path) -> None:
    audit = AuditStore(tmp_path / "audit.sqlite3")
    config = _make_remote_config(host="127.0.0.1", allowlist=("10.0.0.0/8",))
    app = _make_asgi_app(config=config, audit_store=audit)

    transport = httpx.ASGITransport(app=app, client=("10.0.0.5", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 401
    rows = audit.fetch_all()
    assert len(rows) == 1
    assert rows[0]["decision"] == "blocked"


# ---------------------------------------------------------------------------
# S-AUTH-03 — wrong token → 401
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_auth03_wrong_token_returns_401(tmp_path: Path) -> None:
    audit = AuditStore(tmp_path / "audit.sqlite3")
    config = _make_remote_config(host="127.0.0.1", allowlist=("10.0.0.0/8",))
    app = _make_asgi_app(config=config, audit_store=audit)

    transport = httpx.ASGITransport(app=app, client=("10.0.0.5", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/", headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401
    rows = audit.fetch_all()
    assert rows[0]["decision"] == "blocked"


# ---------------------------------------------------------------------------
# S-AUTH-04 — correct token, IP not in allowlist → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_auth04_ip_not_in_allowlist_returns_403(tmp_path: Path) -> None:
    audit = AuditStore(tmp_path / "audit.sqlite3")
    config = _make_remote_config(host="127.0.0.1", allowlist=("10.0.0.0/8",))
    app = _make_asgi_app(config=config, audit_store=audit)

    # Client IP 172.16.0.1 is NOT in 10.0.0.0/8
    transport = httpx.ASGITransport(app=app, client=("172.16.0.1", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/", headers={"Authorization": "Bearer tok"})

    assert response.status_code == 403
    rows = audit.fetch_all()
    assert rows[0]["decision"] == "blocked"


# ---------------------------------------------------------------------------
# S-AUTH-05 — wildcard allowlist + valid token → 200
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_auth05_wildcard_allowlist_allows_any_ip(tmp_path: Path) -> None:
    audit = AuditStore(tmp_path / "audit.sqlite3")
    config = _make_remote_config(host="127.0.0.1", allowlist=("*",))
    app = _make_asgi_app(config=config, audit_store=audit)

    transport = httpx.ASGITransport(app=app, client=("1.2.3.4", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/", headers={"Authorization": "Bearer tok"})

    assert response.status_code == 200
    rows = audit.fetch_all()
    assert rows[0]["decision"] == "allowed"


# ---------------------------------------------------------------------------
# S-AUTH-06 — XFF trusted when socket peer is loopback → leftmost hop used
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_auth06_xff_trusted_loopback_peer_uses_leftmost_hop(tmp_path: Path) -> None:
    audit = AuditStore(tmp_path / "audit.sqlite3")
    # allowlist covers the XFF IP (203.0.113.55 is in a /24)
    config = _make_remote_config(host="127.0.0.1", allowlist=("203.0.113.0/24",))
    app = _make_asgi_app(config=config, audit_store=audit)

    # Socket peer is loopback → XFF is trusted
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/",
            headers={"Authorization": "Bearer tok", "X-Forwarded-For": "203.0.113.55"},
        )

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# S-AUTH-07 — XFF ignored when socket peer is public → socket peer used
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_auth07_xff_ignored_public_peer_uses_socket_peer(tmp_path: Path) -> None:
    audit = AuditStore(tmp_path / "audit.sqlite3")
    # allowlist covers the socket peer (1.2.3.0/24)
    config = _make_remote_config(
        host="1.2.3.4",  # public bind → trust_proxy_headers=False
        allowlist=("1.2.3.0/24",),
        allow_insecure=True,  # public bind needs TLS or allow_insecure
    )
    app = _make_asgi_app(config=config, audit_store=audit)

    transport = httpx.ASGITransport(app=app, client=("1.2.3.4", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/",
            headers={
                "Authorization": "Bearer tok",
                "X-Forwarded-For": "127.0.0.1",  # spoofed loopback — must be ignored
            },
        )

    # Socket peer 1.2.3.4 is in 1.2.3.0/24 → authorized
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# S-AUTH-08 — XFF spoofing rejected: public peer + spoofed loopback + not in allowlist
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_auth08_xff_spoof_rejected_public_peer_not_in_allowlist(tmp_path: Path) -> None:
    audit = AuditStore(tmp_path / "audit.sqlite3")
    config = _make_remote_config(
        host="5.5.5.5",  # public bind
        allowlist=("10.0.0.0/8",),
        allow_insecure=True,
    )
    app = _make_asgi_app(config=config, audit_store=audit)

    # Socket peer 5.5.5.5 is NOT in 10.0.0.0/8, XFF spoof of loopback is ignored
    transport = httpx.ASGITransport(app=app, client=("5.5.5.5", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/",
            headers={
                "Authorization": "Bearer tok",
                "X-Forwarded-For": "127.0.0.1",
            },
        )

    assert response.status_code == 403
    rows = audit.fetch_all()
    assert rows[0]["decision"] == "blocked"


# ---------------------------------------------------------------------------
# S-AUTH-09 — audit event always recorded on block
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_auth09_audit_event_recorded_on_every_block(tmp_path: Path) -> None:
    audit = AuditStore(tmp_path / "audit.sqlite3")
    config = _make_remote_config(host="127.0.0.1", allowlist=("10.0.0.0/8",))
    app = _make_asgi_app(config=config, audit_store=audit)

    transport = httpx.ASGITransport(app=app, client=("10.0.0.5", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # missing token
        await client.get("/")
        # wrong token
        await client.get("/", headers={"Authorization": "Bearer wrong"})

    # IP blocked (different IP not in 10/8)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("172.16.0.1", 12345)),
        base_url="http://test",
    ) as client:
        await client.get("/", headers={"Authorization": "Bearer tok"})

    rows = audit.fetch_all()
    assert len(rows) == 3
    assert all(r["decision"] == "blocked" for r in rows)
    assert all(r["event_type"] == "remote.authorize" for r in rows)


# ---------------------------------------------------------------------------
# S-AUTH-10 — bearer token redacted in audit context
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_auth10_bearer_token_redacted_in_audit(tmp_path: Path) -> None:
    audit = AuditStore(tmp_path / "audit.sqlite3")
    config = _make_remote_config(host="127.0.0.1", allowlist=("10.0.0.0/8",))
    app = _make_asgi_app(config=config, audit_store=audit)

    transport = httpx.ASGITransport(app=app, client=("10.0.0.5", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/", headers={"Authorization": "Bearer tok"})

    rows = audit.fetch_all()
    context = json.loads(rows[0]["context_json"])
    assert context["authorization"] == REDACTED
    # Raw token must not appear anywhere in the serialised context
    assert "tok" not in json.dumps(context)
