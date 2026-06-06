"""WU9 — Trading tool registration and server/app wiring tests.

Tests verify:
- create_server() without trading deps → no trading tool names (AT-10-a)
- create_server() with all trading deps → all 13 trading tool names present (AT-10-b)
- build_runtime() returns server with trading tools present (CO-1-a/b)
- build_runtime() parses YUGEN_MT5_REAL_ACCOUNT_CONSENT env var (WU9-I4)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.fake_mt5 import FakeMT5Backend
from yugen_mt5_mcp.app import build_runtime
from yugen_mt5_mcp.audit import AuditStore
from yugen_mt5_mcp.config import AppConfig, RiskConfig
from yugen_mt5_mcp.market_data import MarketDataService
from yugen_mt5_mcp.mt5_adapter import MT5Adapter
from yugen_mt5_mcp.risk import RiskPolicy
from yugen_mt5_mcp.server import TRADING_TOOL_NAMES, create_server
from yugen_mt5_mcp.session import SessionRiskStore
from yugen_mt5_mcp.trading import BulkTradeService, TradingService

CONSENT_ENV = "YUGEN_MT5_REAL_ACCOUNT_CONSENT"


def _build_trading_deps(
    tmp_path: Path,
    *,
    allow_live_trading: bool = True,
    allow_real_accounts: bool = True,
) -> tuple[MarketDataService, TradingService, BulkTradeService, SessionRiskStore, AppConfig]:
    backend = FakeMT5Backend()
    adapter = MT5Adapter(backend=backend)
    audit_store = AuditStore(tmp_path / "audit.sqlite3")
    config = AppConfig(
        risk=RiskConfig(
            allowed_symbols=("EURUSD",),
            allow_live_trading=allow_live_trading,
            allow_real_accounts=allow_real_accounts,
        )
    )
    session_store = SessionRiskStore()
    risk_policy = RiskPolicy(config=config, session_store=session_store, audit_store=audit_store)
    market_data = MarketDataService(config=config, adapter=adapter, audit_store=audit_store)
    trading_service = TradingService(
        adapter=adapter,
        risk_policy=risk_policy,
        audit_store=audit_store,
    )
    bulk_service = BulkTradeService(
        trading_service=trading_service,
        adapter=adapter,
        audit_store=audit_store,
    )
    return market_data, trading_service, bulk_service, session_store, config


# --- WU9-T1: no trading deps → no trading tool names ---


def test_create_server_without_trading_deps_has_no_trading_tools(tmp_path: Path) -> None:
    backend = FakeMT5Backend()
    adapter = MT5Adapter(backend=backend)
    audit_store = AuditStore(tmp_path / "audit.sqlite3")
    config = AppConfig(risk=RiskConfig(allowed_symbols=("EURUSD",)))
    market_data = MarketDataService(config=config, adapter=adapter, audit_store=audit_store)

    mcp = create_server(market_data)

    async def get_tool_names() -> list[str]:
        from fastmcp.client import Client

        async with Client(mcp) as client:
            tools = await client.list_tools()
            return [tool.name for tool in tools]

    tool_names = asyncio.run(get_tool_names())
    for name in TRADING_TOOL_NAMES:
        assert name not in tool_names, (
            f"Trading tool {name!r} should not be registered without deps"
        )


# --- WU9-T2: with trading deps → all 13 trading tool names present ---


def test_create_server_with_trading_deps_registers_all_13_tools(tmp_path: Path) -> None:
    market_data, trading_service, bulk_service, session_store, config = _build_trading_deps(
        tmp_path
    )

    mcp = create_server(
        market_data,
        trading_service=trading_service,
        bulk_service=bulk_service,
        session_store=session_store,
        config=config,
    )

    async def get_tool_names() -> list[str]:
        from fastmcp.client import Client

        async with Client(mcp) as client:
            tools = await client.list_tools()
            return [tool.name for tool in tools]

    tool_names = asyncio.run(get_tool_names())
    for name in TRADING_TOOL_NAMES:
        assert name in tool_names, f"Trading tool {name!r} should be registered with deps"
    # Read-only tools must still be present
    for read_name in (
        "list_symbols",
        "get_tick",
        "get_candles",
        "get_account",
        "list_positions",
        "list_orders",
        "get_history",
    ):
        assert read_name in tool_names, f"Read-only tool {read_name!r} must remain present"


def test_trading_tool_names_do_not_overlap_read_only_tool_names() -> None:
    from yugen_mt5_mcp.server import READ_ONLY_TOOL_NAMES

    overlap = set(TRADING_TOOL_NAMES) & set(READ_ONLY_TOOL_NAMES)
    assert overlap == set(), f"Tool name overlap: {overlap}"


def test_trading_tool_names_tuple_contains_all_13() -> None:
    assert len(TRADING_TOOL_NAMES) == 13
    expected = {
        "place_market_order",
        "place_pending_order",
        "modify_position",
        "modify_pending_order",
        "close_position",
        "cancel_pending_order",
        "acknowledge_real_account",
        "close_all_positions",
        "close_all_by_symbol",
        "close_all_profitable",
        "close_all_losing",
        "cancel_all_pending",
        "cancel_all_pending_by_symbol",
    }
    assert set(TRADING_TOOL_NAMES) == expected


# --- WU9-T3: build_runtime() returns server with trading tools present ---


def test_build_runtime_includes_trading_tools(tmp_path: Path) -> None:
    async def get_tool_names(server: object) -> list[str]:
        from fastmcp import FastMCP
        from fastmcp.client import Client

        assert isinstance(server, FastMCP)
        async with Client(server) as client:  # type: ignore[arg-type]
            tools = await client.list_tools()
            return [tool.name for tool in tools]

    def server_factory_spy(market_data: Any, doctor_service: Any) -> Any:
        # We can't intercept create_server signature change here,
        # so we verify via the default path
        raise NotImplementedError("use default path")

    runtime = build_runtime(
        env={"YUGEN_MT5_ALLOWED_SYMBOLS": "EURUSD"},
        audit_path=tmp_path / "audit.sqlite3",
        adapter_factory=lambda: MT5Adapter(backend=FakeMT5Backend()),
    )
    tool_names = asyncio.run(get_tool_names(runtime.server))

    for name in TRADING_TOOL_NAMES:
        assert name in tool_names, f"build_runtime server missing trading tool: {name!r}"


def test_build_runtime_read_only_tools_unaffected(tmp_path: Path) -> None:
    runtime = build_runtime(
        env={"YUGEN_MT5_ALLOWED_SYMBOLS": "EURUSD"},
        audit_path=tmp_path / "audit.sqlite3",
        adapter_factory=lambda: MT5Adapter(backend=FakeMT5Backend()),
    )

    async def get_tool_names(server: object) -> list[str]:
        from fastmcp import FastMCP
        from fastmcp.client import Client

        assert isinstance(server, FastMCP)
        async with Client(server) as client:  # type: ignore[arg-type]
            tools = await client.list_tools()
            return [tool.name for tool in tools]

    tool_names = asyncio.run(get_tool_names(runtime.server))
    for read_name in (
        "list_symbols",
        "get_tick",
        "get_candles",
        "get_account",
        "list_positions",
        "list_orders",
        "get_history",
    ):
        assert read_name in tool_names


# --- WU9-T4: build_runtime() parses YUGEN_MT5_REAL_ACCOUNT_CONSENT env var ---


def test_build_runtime_parses_consent_env_var_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yugen_mt5_mcp.app as app_module

    captured_config: AppConfig | None = None

    original_create_server = app_module.create_server

    def capture_create_server(market_data: Any, doctor_service: Any = None, **kwargs: Any) -> Any:
        nonlocal captured_config
        captured_config = market_data._config
        return original_create_server(market_data, doctor_service, **kwargs)

    monkeypatch.setattr(app_module, "create_server", capture_create_server)

    build_runtime(
        env={
            "YUGEN_MT5_ALLOWED_SYMBOLS": "EURUSD",
            CONSENT_ENV: "true",
        },
        audit_path=tmp_path / "audit.sqlite3",
        adapter_factory=lambda: MT5Adapter(backend=FakeMT5Backend()),
    )

    assert captured_config is not None
    assert captured_config.risk.real_account_consent_env is True


def test_build_runtime_consent_env_var_false_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yugen_mt5_mcp.app as app_module

    captured_config: AppConfig | None = None

    original_create_server = app_module.create_server

    def capture_create_server(market_data: Any, doctor_service: Any = None, **kwargs: Any) -> Any:
        nonlocal captured_config
        captured_config = market_data._config
        return original_create_server(market_data, doctor_service, **kwargs)

    monkeypatch.setattr(app_module, "create_server", capture_create_server)

    build_runtime(
        env={"YUGEN_MT5_ALLOWED_SYMBOLS": "EURUSD"},
        audit_path=tmp_path / "audit.sqlite3",
        adapter_factory=lambda: MT5Adapter(backend=FakeMT5Backend()),
    )

    assert captured_config is not None
    assert captured_config.risk.real_account_consent_env is False
