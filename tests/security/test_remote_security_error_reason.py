"""T-03: Tests for RemoteSecurityError typed reason attribute."""

from __future__ import annotations

from pathlib import Path

import pytest

from yugen_mt5_mcp.audit import AuditStore
from yugen_mt5_mcp.config import RemoteTransportConfig
from yugen_mt5_mcp.security import RemoteSecurityError, RemoteSecurityManager


def _manager(tmp_path: Path, **overrides: object) -> RemoteSecurityManager:
    """Build a RemoteSecurityManager with loopback trusted-local config."""
    defaults: dict[str, object] = {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8765,
        "bearer_token": "test-token",
        "tls_terminated": False,
        "allowlist": ("127.0.0.1/32", "10.0.0.0/8"),
    }
    defaults.update(overrides)
    cfg = RemoteTransportConfig(**defaults)  # type: ignore[arg-type]
    audit_store = AuditStore(tmp_path / "audit.sqlite3")
    return RemoteSecurityManager(cfg, audit_store=audit_store)


class TestRemoteSecurityErrorReason:
    def test_error_has_reason_attribute(self) -> None:
        err = RemoteSecurityError("some error", reason="config_error")
        assert err.reason == "config_error"

    def test_reason_defaults_to_config_error(self) -> None:
        err = RemoteSecurityError("some error")
        assert err.reason == "config_error"

    def test_missing_token_reason(self, tmp_path: Path) -> None:
        manager = _manager(tmp_path)
        with pytest.raises(RemoteSecurityError) as exc_info:
            manager.authorize(
                request_id="r1",
                client_ip="10.0.0.1",
                authorization_header=None,
            )
        assert exc_info.value.reason == "missing_token"

    def test_invalid_token_reason(self, tmp_path: Path) -> None:
        manager = _manager(tmp_path)
        with pytest.raises(RemoteSecurityError) as exc_info:
            manager.authorize(
                request_id="r2",
                client_ip="10.0.0.1",
                authorization_header="Bearer wrong",
            )
        assert exc_info.value.reason == "invalid_token"

    def test_ip_blocked_reason(self, tmp_path: Path) -> None:
        manager = _manager(tmp_path)
        with pytest.raises(RemoteSecurityError) as exc_info:
            manager.authorize(
                request_id="r3",
                client_ip="1.2.3.4",  # not in allowlist
                authorization_header="Bearer test-token",
            )
        assert exc_info.value.reason == "ip_blocked"
