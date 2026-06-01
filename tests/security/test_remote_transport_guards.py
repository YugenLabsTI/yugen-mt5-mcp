from __future__ import annotations

import json
from pathlib import Path

import pytest

from yugen_mt5_mcp.audit import REDACTED, AuditStore
from yugen_mt5_mcp.config import AppConfig, ConfigError
from yugen_mt5_mcp.security import RemoteRequestIdentity, RemoteSecurityError, RemoteSecurityManager


def test_remote_security_manager_allows_caddy_terminated_bearer_requests(tmp_path: Path) -> None:
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


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {
                "transport": {
                    "mode": "remote",
                    "remote": {
                        "enabled": True,
                        "host": "127.0.0.1",
                        "port": 9443,
                        "tls_terminated": True,
                        "bearer_token": "secret-token",
                        "allowlist": ["127.0.0.1/32"],
                    },
                }
            },
            "Caddy",
        ),
        (
            {
                "transport": {
                    "mode": "remote",
                    "remote": {
                        "enabled": True,
                        "host": "8.8.8.8",
                        "port": 9443,
                        "tls_terminated": True,
                        "reverse_proxy": "caddy",
                        "bearer_token": "secret-token",
                        "allowlist": ["127.0.0.1/32"],
                    },
                }
            },
            "private or loopback",
        ),
        (
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
                        "allowlist": ["0.0.0.0/0"],
                    },
                }
            },
            "allow all addresses",
        ),
    ],
)
def test_remote_mode_rejects_unsafe_startup_matrix(
    payload: dict[str, object], message: str
) -> None:
    with pytest.raises(ConfigError, match=message):
        AppConfig.from_mapping(payload)
