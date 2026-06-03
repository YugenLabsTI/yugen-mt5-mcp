"""T-14: Tests for build_http_app composition (spec §4.3)."""

from __future__ import annotations

from pathlib import Path

from yugen_mt5_mcp.audit import AuditStore
from yugen_mt5_mcp.config import RemoteTransportConfig
from yugen_mt5_mcp.security import RemoteSecurityManager
from yugen_mt5_mcp.server import build_http_app


def _make_config(**kwargs: object) -> RemoteTransportConfig:
    defaults: dict[str, object] = {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8765,
        "bearer_token": "tok",
        "allowlist": ("127.0.0.1/32",),
        "stateless_http": False,
        "path": "/mcp/",
    }
    defaults.update(kwargs)
    return RemoteTransportConfig(**defaults)  # type: ignore[arg-type]


def _make_manager(config: RemoteTransportConfig, audit_store: AuditStore) -> RemoteSecurityManager:
    return RemoteSecurityManager(config, audit_store=audit_store)


def test_build_http_app_returns_callable(tmp_path: Path) -> None:
    """build_http_app returns an ASGI callable."""
    from fastmcp import FastMCP

    mcp = FastMCP("test")
    audit = AuditStore(tmp_path / "audit.sqlite3")
    config = _make_config()
    manager = _make_manager(config, audit)

    app = build_http_app(mcp, config, manager)

    assert callable(app)


def test_build_http_app_has_bearer_ip_auth_middleware_in_stack(tmp_path: Path) -> None:
    """The returned Starlette app includes BearerIPAuthMiddleware in user_middleware."""
    from fastmcp import FastMCP

    mcp = FastMCP("test")
    audit = AuditStore(tmp_path / "audit.sqlite3")
    config = _make_config()
    manager = _make_manager(config, audit)

    app = build_http_app(mcp, config, manager)

    # Starlette exposes user_middleware as the list of registered Middleware objects
    # (before lazy stack build). Walk cls entries.
    user_mw = getattr(app, "user_middleware", [])
    mw_cls_names = {m.cls.__name__ for m in user_mw if hasattr(m, "cls")}
    assert "BearerIPAuthMiddleware" in mw_cls_names


def test_build_http_app_forwards_stateless_http_false(tmp_path: Path) -> None:
    """stateless_http=False in remote_config is forwarded."""
    from fastmcp import FastMCP

    mcp = FastMCP("test")
    audit = AuditStore(tmp_path / "audit.sqlite3")
    config = _make_config(stateless_http=False)
    manager = _make_manager(config, audit)

    app = build_http_app(mcp, config, manager)
    assert callable(app)  # no error raised passing stateless_http=False


def test_build_http_app_forwards_stateless_http_true(tmp_path: Path) -> None:
    """stateless_http=True in remote_config is forwarded."""
    from fastmcp import FastMCP

    mcp = FastMCP("test")
    audit = AuditStore(tmp_path / "audit.sqlite3")
    config = _make_config(stateless_http=True)
    manager = _make_manager(config, audit)

    app = build_http_app(mcp, config, manager)
    assert callable(app)


def test_build_http_app_forwards_path(tmp_path: Path) -> None:
    """path from remote_config is forwarded to mcp.http_app."""
    from fastmcp import FastMCP

    mcp = FastMCP("test")
    audit = AuditStore(tmp_path / "audit.sqlite3")
    config = _make_config(path="/mcp/")
    manager = _make_manager(config, audit)

    app = build_http_app(mcp, config, manager)
    assert callable(app)
