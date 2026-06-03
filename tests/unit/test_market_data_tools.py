from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict, cast

import pytest

from tests.fakes.fake_mt5 import FakeMT5Backend, FakeMT5Symbol, FakeMT5Tick
from yugen_mt5_mcp.audit import AuditStore
from yugen_mt5_mcp.config import AppConfig, RiskConfig
from yugen_mt5_mcp.doctor import DoctorService, create_default_doctor
from yugen_mt5_mcp.market_data import MarketDataError, MarketDataService
from yugen_mt5_mcp.mt5_adapter import MT5Adapter
from yugen_mt5_mcp.server import create_server


class CandleRequest(TypedDict):
    symbol: str
    timeframe: str
    limit: int


def build_service(
    tmp_path: Path,
    *,
    allowed_symbols: tuple[str, ...] = ("EURUSD",),
) -> MarketDataService:
    config = AppConfig(risk=RiskConfig(allowed_symbols=allowed_symbols))
    backend = FakeMT5Backend()
    adapter = MT5Adapter(backend=backend)
    audit_store = AuditStore(tmp_path)
    return MarketDataService(config=config, adapter=adapter, audit_store=audit_store)


def build_doctor(tmp_path: Path) -> DoctorService:
    audit_path = tmp_path / "audit.sqlite3"
    return create_default_doctor(
        config=AppConfig(risk=RiskConfig(allowed_symbols=("EURUSD",))),
        audit_store=AuditStore(audit_path),
        adapter=MT5Adapter(backend=FakeMT5Backend()),
        read_tool_names=(
            "list_symbols",
            "get_tick",
            "get_candles",
            "get_account",
            "list_positions",
            "list_orders",
            "get_history",
        ),
    )


def test_get_candles_returns_normalized_bars(tmp_path: Path) -> None:
    service = build_service(tmp_path / "audit.sqlite3")

    candles = service.get_candles(symbol="EURUSD", timeframe="M1", limit=2)

    assert [candle.close for candle in candles] == [1.105, 1.109]
    assert candles[0].spread == 12


def test_wildcard_allowed_symbols_permits_read_tools(tmp_path: Path) -> None:
    service = build_service(tmp_path / "audit.sqlite3", allowed_symbols=("*",))

    tick = service.get_tick(symbol="eurusd")

    assert tick.symbol == "EURUSD"


def test_wildcard_allowed_symbols_preserves_broker_symbol_casing(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.sqlite3"
    config = AppConfig(risk=RiskConfig(allowed_symbols=("*",)))
    backend = FakeMT5Backend()
    backend.symbols.append(FakeMT5Symbol(name="Boom 1000 Index", path="Synthetic"))
    backend.ticks["Boom 1000 Index"] = FakeMT5Tick(
        bid=1000.1,
        ask=1000.2,
        last=1000.15,
        time=1_704_110_400,
    )
    adapter = MT5Adapter(backend=backend)
    service = MarketDataService(
        config=config,
        adapter=adapter,
        audit_store=AuditStore(audit_path),
    )

    tick = service.get_tick(symbol="boom 1000 index")

    assert tick.symbol == "Boom 1000 Index"
    assert backend.selected_symbols[-1] == "Boom 1000 Index"


def test_explicit_allowlist_preserves_configured_symbol_casing(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.sqlite3"
    config = AppConfig(risk=RiskConfig(allowed_symbols=("Boom 1000 Index",)))
    backend = FakeMT5Backend()
    backend.symbols.append(FakeMT5Symbol(name="Boom 1000 Index", path="Synthetic"))
    backend.ticks["Boom 1000 Index"] = FakeMT5Tick(
        bid=1000.1,
        ask=1000.2,
        last=1000.15,
        time=1_704_110_400,
    )
    adapter = MT5Adapter(backend=backend)
    service = MarketDataService(
        config=config,
        adapter=adapter,
        audit_store=AuditStore(audit_path),
    )

    tick = service.get_tick(symbol="BOOM 1000 INDEX")

    assert tick.symbol == "Boom 1000 Index"


def test_no_allowlist_preserves_broker_symbol_casing(tmp_path: Path) -> None:
    """No allowlist configured must NOT uppercase: MT5 symbols are case-sensitive.

    Regression: the no-allowlist fallback used to ``return requested.upper()``,
    turning "Boom 1000 Index" into "BOOM 1000 INDEX" and breaking symbol_select
    for every mixed-case Deriv instrument.
    """
    audit_path = tmp_path / "audit.sqlite3"
    config = AppConfig(risk=RiskConfig(allowed_symbols=()))
    backend = FakeMT5Backend()
    backend.symbols.append(FakeMT5Symbol(name="Boom 1000 Index", path="Synthetic"))
    backend.ticks["Boom 1000 Index"] = FakeMT5Tick(
        bid=1000.1,
        ask=1000.2,
        last=1000.15,
        time=1_704_110_400,
    )
    adapter = MT5Adapter(backend=backend)
    service = MarketDataService(
        config=config,
        adapter=adapter,
        audit_store=AuditStore(audit_path),
    )

    tick = service.get_tick(symbol="boom 1000 index")

    assert tick.symbol == "Boom 1000 Index"
    assert backend.selected_symbols[-1] == "Boom 1000 Index"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"symbol": "GBPUSD", "timeframe": "M1", "limit": 2}, "not allowed"),
        ({"symbol": "EURUSD", "timeframe": "BAD", "limit": 2}, "unsupported timeframe"),
        ({"symbol": "EURUSD", "timeframe": "M1", "limit": 0}, "between 1 and 1000"),
    ],
)
def test_get_candles_rejects_invalid_requests_and_audits(
    tmp_path: Path,
    kwargs: CandleRequest,
    message: str,
) -> None:
    audit_path = tmp_path / "audit.sqlite3"
    service = build_service(audit_path)

    with pytest.raises(MarketDataError, match=message):
        service.get_candles(**kwargs)

    rows = AuditStore(audit_path).fetch_all()
    assert rows[-1]["event_type"] == "market_data.get_candles"
    assert rows[-1]["decision"] == "rejected"


def test_list_positions_includes_account_mode(tmp_path: Path) -> None:
    service = build_service(tmp_path / "audit.sqlite3")

    positions = service.list_positions()

    assert len(positions) == 1
    assert positions[0].account_mode == "hedging"


def test_server_registers_read_tools_and_calls_candles(tmp_path: Path) -> None:
    service = build_service(tmp_path / "audit.sqlite3")
    mcp = create_server(service)

    async def run_tool() -> tuple[list[str], object]:
        from fastmcp.client import Client

        async with Client(mcp) as client:
            tools = await client.list_tools()
            result = await client.call_tool(
                "get_candles",
                {"symbol": "EURUSD", "timeframe": "M1", "limit": 2},
            )
            return [tool.name for tool in tools], result.data

    tool_names, payload = asyncio.run(run_tool())
    candles = cast(list[dict[str, object]], payload)

    assert "get_candles" in tool_names
    assert len(candles) == 2
    assert candles[0]["symbol"] == "EURUSD"


def test_server_registration_preserves_existing_tool_contracts(tmp_path: Path) -> None:
    service = build_service(tmp_path / "audit.sqlite3")
    mcp = create_server(service)

    async def inspect_tools() -> dict[str, object]:
        from fastmcp.client import Client

        async with Client(mcp) as client:
            tools = await client.list_tools()
            return {tool.name: tool.inputSchema for tool in tools}

    tool_schemas = asyncio.run(inspect_tools())

    # REQ-8.2: chart tools are always registered (even when disabled), so we assert
    # membership rather than exact list equality.
    for expected_name in [
        "list_symbols",
        "get_tick",
        "get_candles",
        "get_account",
        "list_positions",
        "list_orders",
        "get_history",
    ]:
        assert expected_name in tool_schemas, f"Expected {expected_name!r} in registered tools"
    assert tool_schemas["list_symbols"] == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    assert tool_schemas["get_tick"] == {
        "type": "object",
        "properties": {"symbol": {"type": "string"}},
        "required": ["symbol"],
        "additionalProperties": False,
    }
    assert tool_schemas["get_candles"] == {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "timeframe": {"type": "string"},
            "limit": {"type": "integer", "default": 100},
        },
        "required": ["symbol", "timeframe"],
        "additionalProperties": False,
    }
    assert tool_schemas["get_account"] == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    assert tool_schemas["list_positions"] == {
        "type": "object",
        "properties": {
            "symbol": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
            }
        },
        "additionalProperties": False,
    }
    assert tool_schemas["list_orders"] == tool_schemas["list_positions"]
    assert tool_schemas["get_history"] == {
        "type": "object",
        "properties": {
            "start": {"type": "string"},
            "end": {"type": "string"},
            "symbol": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
            },
        },
        "required": ["start", "end"],
        "additionalProperties": False,
    }


def test_server_registers_doctor_tool_without_changing_read_tools(tmp_path: Path) -> None:
    service = build_service(tmp_path / "audit.sqlite3")
    doctor_service = build_doctor(tmp_path / "doctor")
    mcp = create_server(service, doctor_service=doctor_service)

    async def inspect_and_call_doctor() -> tuple[list[str], object]:
        from fastmcp.client import Client

        async with Client(mcp) as client:
            tools = await client.list_tools()
            result = await client.call_tool("doctor", {})
            return [tool.name for tool in tools], result.data

    tool_names, payload = asyncio.run(inspect_and_call_doctor())
    report = cast(dict[str, object], payload)

    # REQ-8.2: chart tools are always registered (even when disabled), so we assert
    # membership rather than exact list equality.
    for expected_name in [
        "list_symbols",
        "get_tick",
        "get_candles",
        "get_account",
        "list_positions",
        "list_orders",
        "get_history",
        "doctor",
    ]:
        assert expected_name in tool_names, f"Expected {expected_name!r} in registered tools"
    assert report["status"] == "ok"
    assert isinstance(report["generated_at"], str)
    checks = cast(list[dict[str, object]], report["checks"])
    assert [check["name"] for check in checks] == [
        "config",
        "audit_path",
        "mt5_account",
        "read_tools",
        "runtime_context",
        "real_account_consent",
        "remote_transport",
    ]
    runtime_ctx = next(c for c in checks if c["name"] == "runtime_context")
    assert runtime_ctx["details"] == {
        "transport_mode": "stdio",
        "remote_enabled": False,
        "allowed_symbols": ["EURUSD"],
        "warnings": [],
    }


def test_get_history_returns_orders_and_deals(tmp_path: Path) -> None:
    service = build_service(tmp_path / "audit.sqlite3")

    history = service.get_history(
        start=datetime(2024, 1, 1, 11, 0, tzinfo=UTC),
        end=datetime(2024, 1, 1, 13, 0, tzinfo=UTC),
        symbol="EURUSD",
    )

    assert len(history.deals) == 1
    assert len(history.orders) == 1
    assert history.window.end - history.window.start == timedelta(hours=2)
