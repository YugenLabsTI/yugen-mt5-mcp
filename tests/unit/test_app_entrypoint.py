from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any, Literal

from yugen_mt5_mcp.app import (
    ALLOWED_SYMBOLS_ENV,
    AUDIT_PATH_ENV,
    EntrypointWarning,
    build_runtime,
    emit_warnings,
    parse_allowed_symbols,
    resolve_audit_path,
    run_stdio,
)
from yugen_mt5_mcp.config import AppConfig


class FakeServer:
    def __init__(self) -> None:
        self.run_calls: list[tuple[str | None, bool | None]] = []

    def run(
        self,
        transport: Literal["stdio", "http", "sse", "streamable-http"] | None = None,
        show_banner: bool | None = None,
        **transport_kwargs: Any,
    ) -> None:
        assert transport_kwargs == {}
        self.run_calls.append((transport, show_banner))


def test_parse_allowed_symbols_defaults_to_empty_allowlist() -> None:
    symbols, warnings = parse_allowed_symbols({})

    assert symbols == ()
    assert warnings == ()


def test_parse_allowed_symbols_normalizes_explicit_values() -> None:
    symbols, warnings = parse_allowed_symbols({ALLOWED_SYMBOLS_ENV: " eurusd, XAUUSD ,,"})

    assert symbols == ("EURUSD", "XAUUSD")
    assert warnings == ()


def test_parse_allowed_symbols_accepts_wildcard_with_warning() -> None:
    symbols, warnings = parse_allowed_symbols({ALLOWED_SYMBOLS_ENV: "*"})

    assert symbols == ("*",)
    assert warnings == (
        EntrypointWarning(
            code="allowed_symbols_wildcard",
            message="YUGEN_MT5_ALLOWED_SYMBOLS=* allows every symbol for read tools",
        ),
    )


def test_build_runtime_uses_stdio_defaults_without_real_mt5(tmp_path: Path) -> None:
    created_configs: list[AppConfig] = []

    def adapter_factory() -> object:
        return object()

    def server_factory(config: AppConfig, adapter: object, audit_path: Path) -> FakeServer:
        del adapter
        created_configs.append(config)
        assert audit_path == tmp_path / "audit.sqlite3"
        return FakeServer()

    runtime = build_runtime(
        env={ALLOWED_SYMBOLS_ENV: "EURUSD"},
        audit_path=tmp_path / "audit.sqlite3",
        adapter_factory=adapter_factory,
        server_factory=server_factory,
    )

    assert created_configs[0].risk.allowed_symbols == ("EURUSD",)
    assert runtime.warnings == ()


def test_resolve_audit_path_uses_absolute_env_value() -> None:
    audit_path = Path("C:/Users/sgg10/AppData/Local/Yugen/mt5-mcp/audit.sqlite3")

    resolved = resolve_audit_path({AUDIT_PATH_ENV: str(audit_path)})

    assert resolved == audit_path


def test_resolve_audit_path_uses_default_when_env_is_blank() -> None:
    resolved = resolve_audit_path({AUDIT_PATH_ENV: "   "})

    assert resolved == Path("var/audit.sqlite3")


def test_build_runtime_uses_audit_path_from_env_without_real_mt5(tmp_path: Path) -> None:
    audit_path = tmp_path / "claude" / "audit.sqlite3"

    def adapter_factory() -> object:
        return object()

    def server_factory(config: AppConfig, adapter: object, received_path: Path) -> FakeServer:
        del config, adapter
        assert received_path == audit_path
        return FakeServer()

    build_runtime(
        env={AUDIT_PATH_ENV: str(audit_path)},
        adapter_factory=adapter_factory,
        server_factory=server_factory,
    )


def test_emit_warnings_writes_to_error_stream() -> None:
    stream = StringIO()

    emit_warnings(
        (
            EntrypointWarning(
                code="allowed_symbols_wildcard",
                message="YUGEN_MT5_ALLOWED_SYMBOLS=* allows every symbol for read tools",
            ),
        ),
        stream=stream,
    )

    assert stream.getvalue() == (
        "WARNING [allowed_symbols_wildcard]: "
        "YUGEN_MT5_ALLOWED_SYMBOLS=* allows every symbol for read tools\n"
    )


def test_run_stdio_runs_server_with_stdio_transport() -> None:
    server = FakeServer()

    run_stdio(server)

    assert server.run_calls == [("stdio", True)]
