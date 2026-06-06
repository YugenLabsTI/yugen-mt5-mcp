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
from yugen_mt5_mcp.config import AppConfig, TransportMode
from yugen_mt5_mcp.doctor import DoctorService, DoctorStatus
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
        assert doctor_service.run().status is DoctorStatus.OK
        checks = {check.name: check for check in doctor_service.run().checks}
        assert checks["read_tools"].details == {
            "registered": list(READ_ONLY_TOOL_NAMES)
        }
        assert checks["runtime_context"].details == {
            "transport_mode": "stdio",
            "remote_enabled": False,
            "allowed_symbols": ["EURUSD"],
            "warnings": [],
        }
        return FakeServer()

    runtime = build_runtime(
        env={ALLOWED_SYMBOLS_ENV: "EURUSD"},
        audit_path=tmp_path / "audit.sqlite3",
        adapter_factory=adapter_factory,
        server_factory=server_factory,
    )

    assert created_configs[0].risk.allowed_symbols == ("EURUSD",)
    assert runtime.warnings == ()


def test_build_runtime_parses_live_trading_env_flags_as_true_false(
    tmp_path: Path,
) -> None:
    created_configs: list[AppConfig] = []

    def adapter_factory() -> MT5Adapter:
        return MT5Adapter(backend=FakeMT5Backend())

    def server_factory(market_data: MarketDataService, doctor_service: DoctorService) -> FakeServer:
        created_configs.append(market_data._config)
        # live_trading_gate=WARN when allow_live_trading=true, so overall is WARN (not FAIL)
        assert doctor_service.run().status is not DoctorStatus.FAIL
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
        assert entrypoint_warnings == ()
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

    assert runtime.warnings == (
        EntrypointWarning(
            code="allowed_symbols_wildcard",
            message="YUGEN_MT5_ALLOWED_SYMBOLS=* allows every symbol for reads and trading",
        ),
    )
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


# ---------------------------------------------------------------------------
# T-06: parse_remote_transport_config — env constants + parse scenarios
# S-CFG-01 through S-CFG-07
# ---------------------------------------------------------------------------

_FIVE_ENTRY_DEFAULT = (
    "127.0.0.1/32",
    "::1/128",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
)


def test_s_cfg_01_empty_env_remote_disabled() -> None:
    """S-CFG-01: empty env → enabled=False."""
    from yugen_mt5_mcp.app import parse_remote_transport_config

    result = parse_remote_transport_config({})

    assert result.enabled is False


def test_s_cfg_02_minimal_enable_applies_all_defaults() -> None:
    """S-CFG-02: minimal enable (ENABLED=true, TOKEN=tok) → all defaults applied."""
    from yugen_mt5_mcp.app import parse_remote_transport_config

    result = parse_remote_transport_config(
        {
            "YUGEN_MT5_REMOTE_ENABLED": "true",
            "YUGEN_MT5_REMOTE_BEARER_TOKEN": "tok",
        }
    )

    assert result.enabled is True
    assert result.host == "127.0.0.1"
    assert result.port == 8765
    assert result.bearer_token == "tok"
    assert result.tls_terminated is False
    assert result.allow_insecure is False
    assert result.stateless_http is False
    assert result.allowlist == _FIVE_ENTRY_DEFAULT


def test_s_cfg_03_all_fields_explicit() -> None:
    """S-CFG-03: all fields set explicitly → all match exactly."""
    from yugen_mt5_mcp.app import parse_remote_transport_config

    result = parse_remote_transport_config(
        {
            "YUGEN_MT5_REMOTE_ENABLED": "true",
            "YUGEN_MT5_REMOTE_HOST": "0.0.0.0",
            "YUGEN_MT5_REMOTE_PORT": "9000",
            "YUGEN_MT5_REMOTE_BEARER_TOKEN": "s",
            "YUGEN_MT5_REMOTE_TLS_TERMINATED": "true",
            "YUGEN_MT5_REMOTE_ALLOWLIST": "10.0.0.0/8,*",
            "YUGEN_MT5_REMOTE_ALLOW_INSECURE": "true",
            "YUGEN_MT5_REMOTE_STATELESS_HTTP": "true",
        }
    )

    assert result.enabled is True
    assert result.host == "0.0.0.0"
    assert result.port == 9000
    assert result.bearer_token == "s"
    assert result.tls_terminated is True
    assert result.allowlist == ("10.0.0.0/8", "*")
    assert result.allow_insecure is True
    assert result.stateless_http is True


def test_s_cfg_04_invalid_port_raises_config_error() -> None:
    """S-CFG-04: port=99999 → ConfigError mentioning port."""
    from yugen_mt5_mcp.app import parse_remote_transport_config
    from yugen_mt5_mcp.config import ConfigError

    with pytest.raises(ConfigError, match="port"):
        parse_remote_transport_config({"YUGEN_MT5_REMOTE_PORT": "99999"})


def test_s_cfg_05_non_integer_port_raises_config_error() -> None:
    """S-CFG-05: non-integer port → ConfigError."""
    from yugen_mt5_mcp.app import parse_remote_transport_config
    from yugen_mt5_mcp.config import ConfigError

    with pytest.raises(ConfigError):
        parse_remote_transport_config({"YUGEN_MT5_REMOTE_PORT": "not-a-number"})


def test_s_cfg_06_invalid_cidr_raises_config_error() -> None:
    """S-CFG-06: invalid CIDR in allowlist → ConfigError."""
    from yugen_mt5_mcp.app import parse_remote_transport_config
    from yugen_mt5_mcp.config import ConfigError

    with pytest.raises(ConfigError):
        parse_remote_transport_config({"YUGEN_MT5_REMOTE_ALLOWLIST": "not-a-cidr"})


def test_s_cfg_07_wildcard_only_allowlist_is_valid() -> None:
    """S-CFG-07: ALLOWLIST='*' → allowlist=('*',), no error."""
    from yugen_mt5_mcp.app import parse_remote_transport_config

    result = parse_remote_transport_config({"YUGEN_MT5_REMOTE_ALLOWLIST": "*"})

    assert result.allowlist == ("*",)


def test_s_cfg_both_wildcard_and_cidr_zero_accepted() -> None:
    """Both '*' and '0.0.0.0/0' in allowlist are accepted (locked decision #2)."""
    from yugen_mt5_mcp.app import parse_remote_transport_config

    result = parse_remote_transport_config(
        {"YUGEN_MT5_REMOTE_ALLOWLIST": "*,0.0.0.0/0,::/0"}
    )

    assert result.allowlist == ("*", "0.0.0.0/0", "::/0")


# ---------------------------------------------------------------------------
# T-08: build_runtime transport mode branching
# S-WIRE-01, S-WIRE-02, S-WIRE-03, S-STDIO-01, S-STDIO-02
# ---------------------------------------------------------------------------


def test_s_wire_01_no_remote_enabled_gives_stdio_mode(tmp_path: Path) -> None:
    """S-WIRE-01: no REMOTE_ENABLED → mode==STDIO, remote.enabled==False."""
    runtime = build_runtime(
        env={},
        audit_path=tmp_path / "audit.sqlite3",
        adapter_factory=lambda: __import__(
            "yugen_mt5_mcp.mt5_adapter", fromlist=["MT5Adapter"]
        ).MT5Adapter(backend=FakeMT5Backend()),
        server_factory=lambda md, ds: FakeServer(),
    )

    assert runtime.config.transport.mode is TransportMode.STDIO
    assert runtime.config.transport.remote.enabled is False


def test_s_wire_02_remote_enabled_gives_remote_mode(tmp_path: Path) -> None:
    """S-WIRE-02: REMOTE_ENABLED=true + TOKEN=tok → mode==REMOTE, remote.enabled==True."""
    runtime = build_runtime(
        env={
            "YUGEN_MT5_REMOTE_ENABLED": "true",
            "YUGEN_MT5_REMOTE_BEARER_TOKEN": "tok",
        },
        audit_path=tmp_path / "audit.sqlite3",
        adapter_factory=lambda: __import__(
            "yugen_mt5_mcp.mt5_adapter", fromlist=["MT5Adapter"]
        ).MT5Adapter(backend=FakeMT5Backend()),
        server_factory=lambda md, ds: FakeServer(),
    )

    assert runtime.config.transport.mode is TransportMode.REMOTE
    assert runtime.config.transport.remote.enabled is True


def test_s_wire_03_remote_enabled_without_token_raises_config_error(tmp_path: Path) -> None:
    """S-WIRE-03: REMOTE_ENABLED=true, no TOKEN → ConfigError at build_runtime."""
    from yugen_mt5_mcp.config import ConfigError

    with pytest.raises(ConfigError):
        build_runtime(
            env={"YUGEN_MT5_REMOTE_ENABLED": "true"},
            audit_path=tmp_path / "audit.sqlite3",
            adapter_factory=lambda: __import__(
                "yugen_mt5_mcp.mt5_adapter", fromlist=["MT5Adapter"]
            ).MT5Adapter(backend=FakeMT5Backend()),
            server_factory=lambda md, ds: FakeServer(),
        )


def test_s_stdio_02_build_runtime_empty_env_no_error(tmp_path: Path) -> None:
    """S-STDIO-02: build_runtime({}) returns valid RuntimeApp with no error."""
    runtime = build_runtime(
        env={},
        audit_path=tmp_path / "audit.sqlite3",
        adapter_factory=lambda: __import__(
            "yugen_mt5_mcp.mt5_adapter", fromlist=["MT5Adapter"]
        ).MT5Adapter(backend=FakeMT5Backend()),
        server_factory=lambda md, ds: FakeServer(),
    )

    assert runtime.server is not None
    assert runtime.config is not None
    assert runtime.audit_store is not None


def test_runtime_app_exposes_config_and_audit_store_fields(tmp_path: Path) -> None:
    """RuntimeApp exposes config: AppConfig and audit_store: AuditStore fields."""
    runtime = build_runtime(
        env={},
        audit_path=tmp_path / "audit.sqlite3",
        adapter_factory=lambda: __import__(
            "yugen_mt5_mcp.mt5_adapter", fromlist=["MT5Adapter"]
        ).MT5Adapter(backend=FakeMT5Backend()),
        server_factory=lambda md, ds: FakeServer(),
    )

    assert isinstance(runtime.config, AppConfig)
    assert isinstance(runtime.audit_store, AuditStore)


# ---------------------------------------------------------------------------
# T-18: main() choosing run_remote vs run_stdio (monkeypatched uvicorn)
# ---------------------------------------------------------------------------


def test_s_stdio_01_main_calls_run_stdio_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S-STDIO-01: main() with no remote env → run_stdio called, run_remote NOT called."""
    run_stdio_calls: list[object] = []
    run_remote_calls: list[object] = []

    fake_server = FakeServer()

    def fake_build_runtime(**kwargs: object) -> object:
        from dataclasses import dataclass

        @dataclass(slots=True, frozen=True)
        class _FakeRuntimeApp:
            server: object
            warnings: tuple
            config: object
            audit_store: object

        from yugen_mt5_mcp.config import AppConfig, TransportConfig, TransportMode

        fake_config = AppConfig(transport=TransportConfig(mode=TransportMode.STDIO))
        from yugen_mt5_mcp.audit import AuditStore

        fake_audit_store = AuditStore(tmp_path / "audit.sqlite3")
        return _FakeRuntimeApp(
            server=fake_server,
            warnings=(),
            config=fake_config,
            audit_store=fake_audit_store,
        )

    monkeypatch.setattr(app_module, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(app_module, "run_stdio", lambda srv: run_stdio_calls.append(srv))
    monkeypatch.setattr(
        app_module,
        "run_remote",
        lambda srv, cfg, audit_store: run_remote_calls.append((srv, cfg, audit_store)),
    )

    app_module.main()

    assert len(run_stdio_calls) == 1
    assert len(run_remote_calls) == 0


def test_s_wire_main_calls_run_remote_when_remote_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() with REMOTE_ENABLED=true + TOKEN=tok → run_remote called, run_stdio NOT called."""
    run_stdio_calls: list[object] = []
    run_remote_calls: list[tuple[object, object, object]] = []

    fake_server = FakeServer()

    def fake_build_runtime(**kwargs: object) -> object:
        from dataclasses import dataclass

        @dataclass(slots=True, frozen=True)
        class _FakeRuntimeApp:
            server: object
            warnings: tuple
            config: object
            audit_store: object

        from yugen_mt5_mcp.config import (
            AppConfig,
            RemoteTransportConfig,
            TransportConfig,
            TransportMode,
        )

        remote_cfg = RemoteTransportConfig(
            enabled=True,
            host="127.0.0.1",
            port=8765,
            bearer_token="tok",
            allowlist=("127.0.0.1/32",),
        )
        fake_config = AppConfig(
            transport=TransportConfig(mode=TransportMode.REMOTE, remote=remote_cfg)
        )
        from yugen_mt5_mcp.audit import AuditStore

        fake_audit_store = AuditStore(tmp_path / "audit.sqlite3")
        return _FakeRuntimeApp(
            server=fake_server,
            warnings=(),
            config=fake_config,
            audit_store=fake_audit_store,
        )

    monkeypatch.setattr(app_module, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(app_module, "run_stdio", lambda srv: run_stdio_calls.append(srv))
    monkeypatch.setattr(
        app_module,
        "run_remote",
        lambda srv, cfg, audit_store: run_remote_calls.append((srv, cfg, audit_store)),
    )

    app_module.main()

    assert len(run_remote_calls) == 1
    assert len(run_stdio_calls) == 0
    called_server, called_cfg, called_audit_store = run_remote_calls[0]
    assert called_server is fake_server
    assert called_cfg.host == "127.0.0.1"
    assert called_cfg.port == 8765


def test_run_remote_calls_uvicorn_run_with_correct_host_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_remote: uvicorn.run is called with the ASGI app, correct host and port."""
    import types

    uvicorn_calls: list[dict[str, object]] = []

    # Build a fake uvicorn module so run_remote's local import resolves
    fake_uvicorn = types.ModuleType("uvicorn")

    def fake_uvicorn_run(app: object, *, host: str, port: int, **kwargs: object) -> None:
        uvicorn_calls.append({"app": app, "host": host, "port": port})

    fake_uvicorn.run = fake_uvicorn_run  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "uvicorn", fake_uvicorn)

    from yugen_mt5_mcp.app import run_remote
    from yugen_mt5_mcp.audit import AuditStore
    from yugen_mt5_mcp.config import RemoteTransportConfig

    fake_server = FakeServer()
    remote_cfg = RemoteTransportConfig(
        enabled=True,
        host="127.0.0.1",
        port=8765,
        bearer_token="tok",
        allowlist=("127.0.0.1/32",),
    )
    audit_store = AuditStore(tmp_path / "audit.sqlite3")

    # Monkeypatch build_http_app and RemoteSecurityManager so no real ASGI app is built
    import yugen_mt5_mcp.app as app_mod

    monkeypatch.setattr(app_mod, "build_http_app", lambda srv, cfg, mgr: object())

    import yugen_mt5_mcp.security as security_mod

    class FakeManager:
        def __init__(self, cfg: object, *, audit_store: object) -> None:
            pass

    monkeypatch.setattr(security_mod, "RemoteSecurityManager", FakeManager)

    run_remote(fake_server, remote_cfg, audit_store)

    assert len(uvicorn_calls) == 1
    assert uvicorn_calls[0]["host"] == "127.0.0.1"
    assert uvicorn_calls[0]["port"] == 8765
