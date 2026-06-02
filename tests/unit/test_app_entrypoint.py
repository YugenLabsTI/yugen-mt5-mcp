from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any, Literal

import pytest

import yugen_mt5_mcp.app as app_module
from tests.fakes.fake_mt5 import FakeMT5Backend
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
from yugen_mt5_mcp.audit import AuditStore
from yugen_mt5_mcp.config import AppConfig
from yugen_mt5_mcp.doctor import DoctorService
from yugen_mt5_mcp.market_data import MarketDataService
from yugen_mt5_mcp.mt5_adapter import MT5Adapter
from yugen_mt5_mcp.server import READ_ONLY_TOOL_NAMES


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


def test_parse_allowed_symbols_preserves_explicit_values() -> None:
    symbols, warnings = parse_allowed_symbols({ALLOWED_SYMBOLS_ENV: " eurusd, Boom 1000 Index ,,"})

    assert symbols == ("eurusd", "Boom 1000 Index")
    assert warnings == ()


def test_parse_allowed_symbols_accepts_wildcard_with_warning() -> None:
    symbols, warnings = parse_allowed_symbols({ALLOWED_SYMBOLS_ENV: "*"})

    assert symbols == ("*",)
    assert warnings == (
        EntrypointWarning(
            code="allowed_symbols_wildcard",
            message="YUGEN_MT5_ALLOWED_SYMBOLS=* allows every symbol for reads and trading",
        ),
    )


def test_build_runtime_injected_server_factory_receives_market_data_and_doctor_service(
    tmp_path: Path,
) -> None:
    created_configs: list[AppConfig] = []

    def adapter_factory() -> MT5Adapter:
        return MT5Adapter(backend=FakeMT5Backend())

    def server_factory(market_data: MarketDataService, doctor_service: DoctorService) -> FakeServer:
        created_configs.append(market_data._config)
        assert market_data._audit_store.database_path == tmp_path / "audit.sqlite3"
        checks = {check.name: check for check in doctor_service.run().checks}
        assert checks["read_tools"].details == {
            "registered": list(READ_ONLY_TOOL_NAMES)
        }
        return FakeServer()

    runtime = build_runtime(
        env={ALLOWED_SYMBOLS_ENV: "EURUSD"},
        audit_path=tmp_path / "audit.sqlite3",
        adapter_factory=adapter_factory,
        server_factory=server_factory,
    )

    assert created_configs[0].risk.allowed_symbols == ("EURUSD",)
    # chart_bridge_disabled is expected when no secret is set — filter it out.
    non_chart_warnings = tuple(w for w in runtime.warnings if w.code != "chart_bridge_disabled")
    assert non_chart_warnings == ()


def test_build_runtime_parses_live_trading_env_flags_as_true_false(
    tmp_path: Path,
) -> None:
    created_configs: list[AppConfig] = []

    def adapter_factory() -> MT5Adapter:
        return MT5Adapter(backend=FakeMT5Backend())

    def server_factory(market_data: MarketDataService, doctor_service: DoctorService) -> FakeServer:
        created_configs.append(market_data._config)
        return FakeServer()

    build_runtime(
        env={
            "YUGEN_MT5_ALLOW_LIVE_TRADING": "true",
            "YUGEN_MT5_ALLOW_REAL_ACCOUNTS": "false",
        },
        audit_path=tmp_path / "audit.sqlite3",
        adapter_factory=adapter_factory,
        server_factory=server_factory,
    )

    assert created_configs[0].risk.allow_live_trading is True
    assert created_configs[0].risk.allow_real_accounts is False


def test_build_runtime_default_factory_wires_doctor_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_config: AppConfig | None = None
    captured_audit_store: AuditStore | None = None
    captured_read_tool_names: tuple[str, ...] | None = None
    captured_market_data: MarketDataService | None = None
    captured_doctor_service: object | None = None
    fake_server = FakeServer()
    fake_doctor = object()

    def fake_create_default_doctor(
        *,
        config: AppConfig,
        audit_store: AuditStore,
        adapter: object,
        read_tool_names: tuple[str, ...],
        entrypoint_warnings: tuple[EntrypointWarning, ...],
    ) -> object:
        nonlocal captured_config, captured_audit_store, captured_read_tool_names
        captured_config = config
        captured_audit_store = audit_store
        captured_read_tool_names = read_tool_names
        assert isinstance(adapter, MT5Adapter)
        # chart_bridge_disabled is expected when no secret is set.
        non_chart = tuple(w for w in entrypoint_warnings if w.code != "chart_bridge_disabled")
        assert non_chart == ()
        return fake_doctor

    def fake_create_server(
        market_data: MarketDataService,
        doctor_service: object | None = None,
        **_: object,
    ) -> FakeServer:
        nonlocal captured_market_data, captured_doctor_service
        captured_market_data = market_data
        captured_doctor_service = doctor_service
        return fake_server

    monkeypatch.setattr(app_module, "create_default_doctor", fake_create_default_doctor)
    monkeypatch.setattr(app_module, "create_server", fake_create_server)

    runtime = build_runtime(
        env={ALLOWED_SYMBOLS_ENV: "EURUSD"},
        audit_path=tmp_path / "audit.sqlite3",
        adapter_factory=lambda: MT5Adapter(backend=FakeMT5Backend()),
    )

    assert runtime.server is fake_server
    assert captured_config is not None
    assert captured_audit_store is not None
    assert captured_read_tool_names is not None
    assert captured_market_data is not None
    assert captured_config.risk.allowed_symbols == ("EURUSD",)
    assert captured_audit_store.database_path == tmp_path / "audit.sqlite3"
    assert captured_read_tool_names == READ_ONLY_TOOL_NAMES
    assert captured_doctor_service is fake_doctor
    assert captured_market_data.get_tick(symbol="EURUSD").symbol == "EURUSD"


def test_build_runtime_passes_wildcard_warning_into_doctor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_warnings: tuple[EntrypointWarning, ...] | None = None

    def fake_create_default_doctor(
        *,
        config: AppConfig,
        audit_store: AuditStore,
        adapter: object,
        read_tool_names: tuple[str, ...],
        entrypoint_warnings: tuple[EntrypointWarning, ...],
    ) -> object:
        nonlocal captured_warnings
        assert isinstance(config, AppConfig)
        assert isinstance(audit_store, AuditStore)
        assert isinstance(adapter, MT5Adapter)
        assert read_tool_names == READ_ONLY_TOOL_NAMES
        captured_warnings = entrypoint_warnings
        return object()

    monkeypatch.setattr(app_module, "create_default_doctor", fake_create_default_doctor)
    monkeypatch.setattr(
        app_module,
        "create_server",
        lambda market_data, doctor_service=None, **_: FakeServer(),
    )

    runtime = build_runtime(
        env={ALLOWED_SYMBOLS_ENV: "*"},
        audit_path=tmp_path / "audit.sqlite3",
        adapter_factory=lambda: MT5Adapter(backend=FakeMT5Backend()),
    )

    wildcard_warning = EntrypointWarning(
        code="allowed_symbols_wildcard",
        message="YUGEN_MT5_ALLOWED_SYMBOLS=* allows every symbol for reads and trading",
    )
    assert wildcard_warning in runtime.warnings
    assert captured_warnings == runtime.warnings


def test_resolve_audit_path_uses_absolute_env_value() -> None:
    audit_path = Path("C:/Users/sgg10/AppData/Local/Yugen/mt5-mcp/audit.sqlite3")

    resolved = resolve_audit_path({AUDIT_PATH_ENV: str(audit_path)})

    assert resolved == audit_path


def test_resolve_audit_path_uses_default_when_env_is_blank() -> None:
    resolved = resolve_audit_path({AUDIT_PATH_ENV: "   "})

    assert resolved == Path("var/audit.sqlite3")


def test_build_runtime_uses_audit_path_from_env_without_real_mt5(tmp_path: Path) -> None:
    audit_path = tmp_path / "claude" / "audit.sqlite3"

    def adapter_factory() -> MT5Adapter:
        return MT5Adapter(backend=FakeMT5Backend())

    def server_factory(market_data: MarketDataService, doctor_service: DoctorService) -> FakeServer:
        assert market_data._audit_store.database_path == audit_path
        assert doctor_service.run().checks[1].details["database_path"] == str(audit_path)
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
                message="YUGEN_MT5_ALLOWED_SYMBOLS=* allows every symbol for reads and trading",
            ),
        ),
        stream=stream,
    )

    assert stream.getvalue() == (
        "WARNING [allowed_symbols_wildcard]: "
        "YUGEN_MT5_ALLOWED_SYMBOLS=* allows every symbol for reads and trading\n"
    )


def test_run_stdio_runs_server_with_stdio_transport() -> None:
    server = FakeServer()

    run_stdio(server)

    assert server.run_calls == [("stdio", True)]
