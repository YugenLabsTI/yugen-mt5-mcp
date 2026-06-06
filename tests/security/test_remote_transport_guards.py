"""T-04: Tiered validator semantics for validate_remote_transport_config.

Replaces the old 3-case parametrize (Caddy-mandatory, 0.0.0.0/0-rejected,
TLS-always-required) with the full S-VAL-01 through S-VAL-12 spec scenarios.

Also keeps the existing RemoteSecurityManager allow/reject tests updated
to use trusted-local configs that no longer require Caddy or TLS.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yugen_mt5_mcp.audit import REDACTED, AuditStore
from yugen_mt5_mcp.config import AppConfig, RemoteTransportConfig
from yugen_mt5_mcp.security import (
    RemoteRequestIdentity,
    RemoteSecurityError,
    RemoteSecurityManager,
    validate_remote_transport_config,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(**kwargs: object) -> RemoteTransportConfig:
    """Build a RemoteTransportConfig directly (bypasses from_mapping validator path)."""
    defaults: dict[str, object] = {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8765,
        "bearer_token": "tok",
        "tls_terminated": False,
        "allowlist": ("127.0.0.1/32",),
        "allow_insecure": False,
        "stateless_http": False,
        "path": "/mcp/",
    }
    defaults.update(kwargs)
    return RemoteTransportConfig(**defaults)  # type: ignore[arg-type]


def _manager(cfg: RemoteTransportConfig, tmp_path: Path) -> RemoteSecurityManager:
    return RemoteSecurityManager(cfg, audit_store=AuditStore(tmp_path / "audit.sqlite3"))


# ---------------------------------------------------------------------------
# Regression: Caddy + TLS config still works (was the original test)
# ---------------------------------------------------------------------------


def test_caddy_tls_config_still_works(tmp_path: Path) -> None:
    """Caddy reverse-proxy + TLS config is still valid (regression guard)."""
    config = AppConfig.from_mapping(
        {
            "transport": {
                "mode": "remote",
                "remote": {
                    "enabled": True,
                    "host": "127.0.0.1",
                    "port": 9443,
                    "tls_terminated": True,
                    "reverse_proxy": "caddy",
                    "bearer_token": "secret-token",
                    "allowlist": ["127.0.0.1/32", "10.0.0.0/24"],
                },
            }
        }
    )
    audit_store = AuditStore(tmp_path / "audit.sqlite3")
    manager = RemoteSecurityManager(config.transport.remote, audit_store=audit_store)

    identity = manager.authorize(
        request_id="req-allow",
        client_ip="10.0.0.8",
        authorization_header="Bearer secret-token",
    )

    assert identity == RemoteRequestIdentity(actor="mcp.remote", client_ip="10.0.0.8")

    rows = audit_store.fetch_all()
    assert len(rows) == 1
    assert rows[0]["event_type"] == "remote.authorize"
    assert rows[0]["decision"] == "allowed"
    payload = json.loads(rows[0]["context_json"])
    assert payload["authorization"] == REDACTED
    assert payload["reverse_proxy"] == "caddy"


# ---------------------------------------------------------------------------
# RemoteSecurityManager: allow/reject tests (updated — no Caddy required)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("authorization_header", "client_ip", "message"),
    [
        (None, "127.0.0.1", "missing bearer token"),
        ("Bearer wrong-token", "127.0.0.1", "invalid bearer token"),
        ("Bearer secret-token", "192.168.1.25", "client IP is not in the allowlist"),
    ],
)
def test_remote_security_manager_rejects_unsafe_requests(
    tmp_path: Path,
    authorization_header: str | None,
    client_ip: str,
    message: str,
) -> None:
    """Manager rejects missing token, wrong token, and IP not in allowlist.

    Fixture now uses trusted-local host (127.0.0.1) without requiring Caddy or TLS.
    """
    config = AppConfig.from_mapping(
        {
            "transport": {
                "mode": "remote",
                "remote": {
                    "enabled": True,
                    "host": "127.0.0.1",
                    "port": 9443,
                    "tls_terminated": False,
                    "bearer_token": "secret-token",
                    "allowlist": ["127.0.0.1/32", "10.0.0.0/24"],
                },
            }
        }
    )
    audit_store = AuditStore(tmp_path / "audit.sqlite3")
    manager = RemoteSecurityManager(config.transport.remote, audit_store=audit_store)

    with pytest.raises(RemoteSecurityError, match=message):
        manager.authorize(
            request_id="req-block",
            client_ip=client_ip,
            authorization_header=authorization_header,
        )

    rows = audit_store.fetch_all()
    assert len(rows) == 1
    assert rows[0]["decision"] == "blocked"
    payload = json.loads(rows[0]["context_json"])
    assert payload["authorization"] == REDACTED or authorization_header is None


# ---------------------------------------------------------------------------
# S-VAL-01 through S-VAL-12 — tiered validator scenarios
# ---------------------------------------------------------------------------


def test_s_val_01_trusted_local_loopback_no_tls_valid() -> None:
    """S-VAL-01: trusted-local 127.0.0.1, no TLS → valid."""
    cfg = _cfg(host="127.0.0.1", tls_terminated=False)
    validate_remote_transport_config(cfg)  # must not raise


def test_s_val_02_trusted_local_private_no_tls_valid() -> None:
    """S-VAL-02: trusted-local private 192.168.x, no TLS → valid."""
    cfg = _cfg(host="192.168.1.5", tls_terminated=False, allowlist=("192.168.0.0/16",))
    validate_remote_transport_config(cfg)  # must not raise


def test_s_val_03_trusted_local_wildcard_allowlist_valid() -> None:
    """S-VAL-03: trusted-local, allowlist=('*',) → valid."""
    cfg = _cfg(host="127.0.0.1", tls_terminated=False, allowlist=("*",))
    validate_remote_transport_config(cfg)  # must not raise


def test_s_val_04_trusted_local_no_token_raises() -> None:
    """S-VAL-04: trusted-local, no token → RemoteSecurityError."""
    cfg = _cfg(host="127.0.0.1", bearer_token=None)
    with pytest.raises(RemoteSecurityError, match="bearer token"):
        validate_remote_transport_config(cfg)


def test_s_val_05_public_no_tls_no_allow_insecure_raises() -> None:
    """S-VAL-05: public 203.0.113.1, no TLS, no ALLOW_INSECURE → error."""
    cfg = _cfg(
        host="203.0.113.1",
        tls_terminated=False,
        allow_insecure=False,
        allowlist=("203.0.113.0/24",),
    )
    with pytest.raises(RemoteSecurityError, match="TLS"):
        validate_remote_transport_config(cfg)


def test_s_val_06_public_no_tls_allow_insecure_valid() -> None:
    """S-VAL-06: public, no TLS, ALLOW_INSECURE=True → valid."""
    cfg = _cfg(
        host="203.0.113.1",
        tls_terminated=False,
        allow_insecure=True,
        allowlist=("203.0.113.0/24",),
    )
    validate_remote_transport_config(cfg)  # must not raise


def test_s_val_07_public_tls_no_allow_insecure_valid() -> None:
    """S-VAL-07: public, TLS=True, no ALLOW_INSECURE → valid. 0.0.0.0/0 now accepted."""
    cfg = _cfg(
        host="8.8.8.8",
        tls_terminated=True,
        allow_insecure=False,
        allowlist=("0.0.0.0/0",),
    )
    validate_remote_transport_config(cfg)  # must not raise


def test_s_val_08_wildcard_bind_no_tls_no_allow_insecure_raises() -> None:
    """S-VAL-08: 0.0.0.0 bind (public tier), no TLS, no ALLOW_INSECURE → error."""
    cfg = _cfg(
        host="0.0.0.0",
        tls_terminated=False,
        allow_insecure=False,
        allowlist=("0.0.0.0/0",),
    )
    with pytest.raises(RemoteSecurityError, match="TLS"):
        validate_remote_transport_config(cfg)


def test_s_val_09_public_tls_wildcard_allowlist_valid() -> None:
    """S-VAL-09: public, TLS, allowlist=('*',) → valid."""
    cfg = _cfg(host="203.0.113.1", tls_terminated=True, allowlist=("*",))
    validate_remote_transport_config(cfg)  # must not raise


def test_s_val_10_empty_allowlist_raises() -> None:
    """S-VAL-10: empty allowlist → error."""
    cfg = _cfg(host="127.0.0.1", allowlist=())
    with pytest.raises(RemoteSecurityError, match="allowlist"):
        validate_remote_transport_config(cfg)


def test_s_val_11_trusted_local_caddy_no_tls_valid() -> None:
    """S-VAL-11: trusted-local, reverse_proxy='caddy', no TLS → valid (Caddy not gating)."""
    cfg = _cfg(host="127.0.0.1", tls_terminated=False, reverse_proxy="caddy")
    validate_remote_transport_config(cfg)  # must not raise


def test_s_val_12_trusted_local_nginx_valid() -> None:
    """S-VAL-12: trusted-local, reverse_proxy='nginx' → valid."""
    cfg = _cfg(host="127.0.0.1", tls_terminated=False, reverse_proxy="nginx")
    validate_remote_transport_config(cfg)  # must not raise


# ---------------------------------------------------------------------------
# _ip_in_allowlist wildcard handling
# ---------------------------------------------------------------------------


def test_ip_in_allowlist_wildcard_star_matches_any() -> None:
    """'*' entry returns True for any IP."""
    from yugen_mt5_mcp.security import _ip_in_allowlist

    assert _ip_in_allowlist("1.2.3.4", ("*",)) is True
    assert _ip_in_allowlist("203.0.113.99", ("*",)) is True
    assert _ip_in_allowlist("::1", ("*",)) is True


def test_ip_in_allowlist_cidr_zero_matches_ipv4() -> None:
    """'0.0.0.0/0' is valid CIDR math — matches any IPv4 (normal CIDR, not rejected)."""
    from yugen_mt5_mcp.security import _ip_in_allowlist

    assert _ip_in_allowlist("1.2.3.4", ("0.0.0.0/0",)) is True
    assert _ip_in_allowlist("255.255.255.255", ("0.0.0.0/0",)) is True


def test_ip_in_allowlist_normal_cidr_match() -> None:
    """Normal CIDR match still works."""
    from yugen_mt5_mcp.security import _ip_in_allowlist

    assert _ip_in_allowlist("10.0.0.5", ("10.0.0.0/8",)) is True
    assert _ip_in_allowlist("192.168.1.5", ("10.0.0.0/8",)) is False


def test_ip_in_allowlist_ipv6_cidr_zero_matches_any() -> None:
    """::/0 is valid CIDR — matches any IPv6."""
    from yugen_mt5_mcp.security import _ip_in_allowlist

    assert _ip_in_allowlist("::1", ("::/0",)) is True
    assert _ip_in_allowlist("2001:db8::1", ("::/0",)) is True
