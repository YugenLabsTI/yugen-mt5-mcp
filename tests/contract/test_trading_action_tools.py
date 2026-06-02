"""WU10 — Contract tests for trading action tools via fastmcp Client.

Tests all 13 tools registered and callable against FakeMT5Backend.
Mirrors the pattern from test_market_data_tools.py.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

import pytest

from tests.fakes.fake_mt5 import (
    FakeMT5Backend,
    FakeMT5Order,
    FakeMT5Position,
    FakeMT5Symbol,
    FakeMT5Tick,
)
from yugen_mt5_mcp.audit import AuditStore
from yugen_mt5_mcp.config import AppConfig, RiskConfig
from yugen_mt5_mcp.market_data import MarketDataService
from yugen_mt5_mcp.mt5_adapter import MT5Adapter
from yugen_mt5_mcp.risk import RiskPolicy
from yugen_mt5_mcp.server import create_server
from yugen_mt5_mcp.session import SessionRiskStore
from yugen_mt5_mcp.trading import BulkTradeService, TradingService

CONSENT_ENV = "YUGEN_MT5_REAL_ACCOUNT_CONSENT"

# Atomic tool names
ATOMIC_TOOL_NAMES = (
    "place_market_order",
    "place_pending_order",
    "modify_position",
    "modify_pending_order",
    "close_position",
    "cancel_pending_order",
    "acknowledge_real_account",
)

# Bulk tool names
BULK_TOOL_NAMES = (
    "close_all_positions",
    "close_all_by_symbol",
    "close_all_profitable",
    "close_all_losing",
    "cancel_all_pending",
    "cancel_all_pending_by_symbol",
)


def _build_server(
    tmp_path: Path,
    *,
    allowed_symbols: tuple[str, ...] = ("EURUSD",),
    allow_live_trading: bool = True,
    allow_real_accounts: bool = True,
    real_account_consent_env: bool = False,
) -> tuple[object, FakeMT5Backend, SessionRiskStore, AuditStore]:
    backend = FakeMT5Backend()
    adapter = MT5Adapter(backend=backend)
    audit_store = AuditStore(tmp_path / "audit.sqlite3")
    config = AppConfig(
        risk=RiskConfig(
            allowed_symbols=allowed_symbols,
            allow_live_trading=allow_live_trading,
            allow_real_accounts=allow_real_accounts,
            real_account_consent_env=real_account_consent_env,
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
    server = create_server(
        market_data,
        trading_service=trading_service,
        bulk_service=bulk_service,
        session_store=session_store,
        config=config,
    )
    return server, backend, session_store, audit_store


def _build_server_no_trading(tmp_path: Path) -> object:
    backend = FakeMT5Backend()
    adapter = MT5Adapter(backend=backend)
    audit_store = AuditStore(tmp_path / "audit.sqlite3")
    config = AppConfig(risk=RiskConfig(allowed_symbols=("EURUSD",)))
    market_data = MarketDataService(config=config, adapter=adapter, audit_store=audit_store)
    return create_server(market_data)


# --- WU10-T1: all 7 atomic tool names present with deps, absent without ---


def test_atomic_tool_names_present_with_deps(tmp_path: Path) -> None:
    server, _, _, _ = _build_server(tmp_path)

    async def get_names() -> list[str]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            tools = await client.list_tools()
            return [t.name for t in tools]

    names = asyncio.run(get_names())
    for name in ATOMIC_TOOL_NAMES:
        assert name in names


def test_atomic_tool_names_absent_without_deps(tmp_path: Path) -> None:
    server = _build_server_no_trading(tmp_path)

    async def get_names() -> list[str]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            tools = await client.list_tools()
            return [t.name for t in tools]

    names = asyncio.run(get_names())
    for name in ATOMIC_TOOL_NAMES:
        assert name not in names


# --- WU10-T2: all 6 bulk tool names present with deps, absent without ---


def test_bulk_tool_names_present_with_deps(tmp_path: Path) -> None:
    server, _, _, _ = _build_server(tmp_path)

    async def get_names() -> list[str]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            tools = await client.list_tools()
            return [t.name for t in tools]

    names = asyncio.run(get_names())
    for name in BULK_TOOL_NAMES:
        assert name in names


def test_bulk_tool_names_absent_without_deps(tmp_path: Path) -> None:
    server = _build_server_no_trading(tmp_path)

    async def get_names() -> list[str]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            tools = await client.list_tools()
            return [t.name for t in tools]

    names = asyncio.run(get_names())
    for name in BULK_TOOL_NAMES:
        assert name not in names


# --- WU10-T3: place_market_order happy path via Client ---


def test_place_market_order_happy_path(tmp_path: Path) -> None:
    server, backend, session_store, _ = _build_server(tmp_path)
    # Pre-ack the session so real-account gate passes
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )

    async def call() -> dict[str, object]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            result = await client.call_tool(
                "place_market_order",
                {
                    "session_id": "s1",
                    "idempotency_key": "k-open-1",
                    "symbol": "EURUSD",
                    "side": "buy",
                    "volume": "0.1",
                },
            )
            return cast(dict[str, object], result.data)

    payload = asyncio.run(call())
    # AT-9-a: all 7 required fields must be present
    for field in (
        "executed_price", "executed_volume", "order", "deal",
        "applied_sl", "applied_tp", "deviation",
    ):
        assert field in payload, f"Missing field: {field!r}"


def test_place_market_order_preserves_broker_symbol_casing(tmp_path: Path) -> None:
    server, backend, session_store, _ = _build_server(
        tmp_path,
        allowed_symbols=("Boom 1000 Index",),
    )
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )
    backend.symbols.append(FakeMT5Symbol(name="Boom 1000 Index", path="Synthetic"))
    backend.ticks["Boom 1000 Index"] = FakeMT5Tick(
        bid=14057.38,
        ask=14058.51,
        last=14058.00,
        volume=10,
        time=1_700_000_000,
    )

    async def call() -> dict[str, object]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            result = await client.call_tool(
                "place_market_order",
                {
                    "session_id": "s1",
                    "idempotency_key": "k-boom-1",
                    "symbol": "Boom 1000 Index",
                    "side": "buy",
                    "volume": "0.2",
                },
            )
            return cast(dict[str, object], result.data)

    payload = asyncio.run(call())

    assert payload["symbol"] == "Boom 1000 Index"
    assert backend.selected_symbols[-1] == "Boom 1000 Index"


def test_place_market_order_uses_allowed_symbol_casing_for_mt5_calls(
    tmp_path: Path,
) -> None:
    server, backend, session_store, _ = _build_server(
        tmp_path,
        allowed_symbols=("Boom 1000 Index",),
    )
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )
    backend.symbols.append(FakeMT5Symbol(name="Boom 1000 Index", path="Synthetic"))
    backend.ticks["Boom 1000 Index"] = FakeMT5Tick(
        bid=14057.38,
        ask=14058.51,
        last=14058.00,
        volume=10,
        time=1_700_000_000,
    )

    async def call() -> dict[str, object]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            result = await client.call_tool(
                "place_market_order",
                {
                    "session_id": "s1",
                    "idempotency_key": "k-boom-2",
                    "symbol": "boom 1000 index",
                    "side": "buy",
                    "volume": "0.2",
                },
            )
            return cast(dict[str, object], result.data)

    payload = asyncio.run(call())

    assert payload["symbol"] == "Boom 1000 Index"
    assert backend.selected_symbols[-1] == "Boom 1000 Index"


def test_place_market_order_accepts_wildcard_allowed_symbols(
    tmp_path: Path,
) -> None:
    server, backend, session_store, _ = _build_server(
        tmp_path,
        allowed_symbols=("*",),
    )
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )
    backend.symbols.append(FakeMT5Symbol(name="Boom 1000 Index", path="Synthetic"))
    backend.ticks["Boom 1000 Index"] = FakeMT5Tick(
        bid=14057.38,
        ask=14058.51,
        last=14058.00,
        volume=10,
        time=1_700_000_000,
    )

    async def call() -> dict[str, object]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            result = await client.call_tool(
                "place_market_order",
                {
                    "session_id": "s1",
                    "idempotency_key": "k-boom-wildcard",
                    "symbol": "Boom 1000 Index",
                    "side": "buy",
                    "volume": "0.2",
                },
            )
            return cast(dict[str, object], result.data)

    payload = asyncio.run(call())

    assert payload["symbol"] == "Boom 1000 Index"
    assert backend.selected_symbols[-1] == "Boom 1000 Index"


def test_place_market_order_wildcard_resolves_broker_symbol_casing(
    tmp_path: Path,
) -> None:
    server, backend, session_store, _ = _build_server(
        tmp_path,
        allowed_symbols=("*",),
    )
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )
    backend.symbols.append(FakeMT5Symbol(name="Boom 1000 Index", path="Synthetic"))
    backend.ticks["Boom 1000 Index"] = FakeMT5Tick(
        bid=14057.38,
        ask=14058.51,
        last=14058.00,
        volume=10,
        time=1_700_000_000,
    )

    async def call() -> dict[str, object]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            result = await client.call_tool(
                "place_market_order",
                {
                    "session_id": "s1",
                    "idempotency_key": "k-boom-wildcard-case",
                    "symbol": "boom 1000 index",
                    "side": "buy",
                    "volume": "0.2",
                },
            )
            return cast(dict[str, object], result.data)

    payload = asyncio.run(call())

    assert payload["symbol"] == "Boom 1000 Index"
    assert backend.selected_symbols[-1] == "Boom 1000 Index"


# --- WU10-T4: place_market_order rejected when live_trading disabled ---


def test_place_market_order_rejected_when_live_trading_disabled(tmp_path: Path) -> None:
    server, _, session_store, audit_store = _build_server(
        tmp_path, allow_live_trading=False, allow_real_accounts=True
    )
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )

    async def call() -> object:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            try:
                result = await client.call_tool(
                    "place_market_order",
                    {
                        "session_id": "s1",
                        "idempotency_key": "k-disabled",
                        "symbol": "EURUSD",
                        "side": "buy",
                        "volume": "0.1",
                    },
                )
                return result.data
            except Exception as exc:
                return str(exc)

    result = asyncio.run(call())
    # Should not succeed — either exception or error payload
    if isinstance(result, dict):
        # If returned as dict, must not have a real order
        assert result.get("order", 0) == 0 or "error" in str(result).lower()


# --- WU10-T5: idempotency replay → duplicate, no re-execution ---


def test_place_market_order_idempotency_replay(tmp_path: Path) -> None:
    server, backend, session_store, audit_store = _build_server(tmp_path)
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )

    async def call_twice() -> tuple[dict[str, object], dict[str, object]]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            params = {
                "session_id": "s1",
                "idempotency_key": "k-idempotent",
                "symbol": "EURUSD",
                "side": "buy",
                "volume": "0.1",
            }
            r1 = await client.call_tool("place_market_order", params)
            r2 = await client.call_tool("place_market_order", params)
            return cast(dict[str, object], r1.data), cast(dict[str, object], r2.data)

    first, second = asyncio.run(call_twice())
    # Both should be present; second is duplicate
    assert first["order"] == second["order"]
    assert second.get("duplicate") is True
    # Only 1 executed event in audit
    events = audit_store.fetch_all()
    executed = [e for e in events if e["decision"] == "executed"]
    assert len(executed) == 1


# --- WU10-T6: place_pending_order happy path → order ticket present ---


def test_place_pending_order_happy_path(tmp_path: Path) -> None:
    server, _, session_store, _ = _build_server(tmp_path)
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )

    async def call() -> dict[str, object]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            result = await client.call_tool(
                "place_pending_order",
                {
                    "session_id": "s1",
                    "idempotency_key": "k-pending-1",
                    "symbol": "EURUSD",
                    "order_type": "buy_limit",
                    "volume": "0.1",
                    "price": 1.09,
                },
            )
            return cast(dict[str, object], result.data)

    payload = asyncio.run(call())
    assert "order" in payload
    assert int(payload["order"]) > 0


# --- WU10-T7: modify_position happy path → applied_sl, applied_tp present ---


def test_modify_position_happy_path(tmp_path: Path) -> None:
    server, _, session_store, _ = _build_server(tmp_path)
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )
    # Backend default position: ticket=1001, symbol=EURUSD

    async def call() -> dict[str, object]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            result = await client.call_tool(
                "modify_position",
                {
                    "session_id": "s1",
                    "idempotency_key": "k-modify-1",
                    "symbol": "EURUSD",
                    "ticket": 1001,
                    "stop_loss": 1.08,
                    "take_profit": 1.12,
                },
            )
            return cast(dict[str, object], result.data)

    payload = asyncio.run(call())
    assert "applied_sl" in payload
    assert "applied_tp" in payload


# --- WU10-T8: close_position full and partial close ---


def test_close_position_full_close(tmp_path: Path) -> None:
    server, backend, session_store, _ = _build_server(tmp_path)
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )
    # ticket=1001, volume=0.2

    async def call() -> dict[str, object]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            result = await client.call_tool(
                "close_position",
                {
                    "session_id": "s1",
                    "idempotency_key": "k-close-full",
                    "symbol": "EURUSD",
                    "ticket": 1001,
                    "volume": "0.2",
                },
            )
            return cast(dict[str, object], result.data)

    payload = asyncio.run(call())
    assert float(payload["executed_volume"]) == pytest.approx(0.2)
    assert int(payload["deal"]) > 0


def test_close_position_partial_close(tmp_path: Path) -> None:
    server, _, session_store, _ = _build_server(tmp_path)
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )

    async def call() -> dict[str, object]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            result = await client.call_tool(
                "close_position",
                {
                    "session_id": "s1",
                    "idempotency_key": "k-close-partial",
                    "symbol": "EURUSD",
                    "ticket": 1001,
                    "volume": "0.1",
                },
            )
            return cast(dict[str, object], result.data)

    payload = asyncio.run(call())
    assert float(payload["executed_volume"]) == pytest.approx(0.1)


# --- WU10-T9: cancel_pending_order happy path + executed audit event ---


def test_cancel_pending_order_happy_path_and_audit(tmp_path: Path) -> None:
    server, backend, session_store, audit_store = _build_server(tmp_path)
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )
    # Backend has order ticket=2001

    async def call() -> dict[str, object]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            result = await client.call_tool(
                "cancel_pending_order",
                {
                    "session_id": "s1",
                    "idempotency_key": "k-cancel-1",
                    "ticket": 2001,
                    "symbol": "EURUSD",
                },
            )
            return cast(dict[str, object], result.data)

    payload = asyncio.run(call())
    assert "order" in payload
    events = audit_store.fetch_all()
    executed = [e for e in events if e["decision"] == "executed"]
    assert len(executed) == 1


# --- WU10-T10: acknowledge_real_account stores ack; subsequent call succeeds ---


def test_acknowledge_real_account_enables_trading(tmp_path: Path) -> None:
    server, _, _, _ = _build_server(tmp_path)

    async def call() -> dict[str, object]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            # First: acknowledge (result unused — side effect is the ack)
            await client.call_tool(
                "acknowledge_real_account",
                {
                    "session_id": "s1",
                    "account_login": 123456,
                    "actor": "user@test.com",
                },
            )
            # Then: place order (should succeed now)
            trade_result = await client.call_tool(
                "place_market_order",
                {
                    "session_id": "s1",
                    "idempotency_key": "k-post-ack",
                    "symbol": "EURUSD",
                    "side": "buy",
                    "volume": "0.1",
                },
            )
            return cast(dict[str, object], trade_result.data)

    payload = asyncio.run(call())
    assert "order" in payload
    assert int(payload["order"]) > 0


# --- WU10-T11: close_all_positions without confirm=True → error ---


def test_close_all_positions_requires_confirm(tmp_path: Path) -> None:
    server, _, session_store, _ = _build_server(tmp_path)
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )

    async def call() -> object:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            try:
                result = await client.call_tool(
                    "close_all_positions",
                    {
                        "session_id": "s1",
                        "idempotency_key": "k-bulk-noconfirm",
                    },
                )
                return result.data
            except Exception as exc:
                return str(exc)

    result = asyncio.run(call())
    # Should fail — either exception message or error in payload
    assert result is not None
    if isinstance(result, dict):
        assert not result.get("succeeded", 0)


# --- WU10-T12: close_all_positions confirm=True → BulkTradeResult shape ---


def test_close_all_positions_success_shape(tmp_path: Path) -> None:
    server, _, session_store, _ = _build_server(tmp_path)
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )
    # Backend has 1 default position

    async def call() -> dict[str, object]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            result = await client.call_tool(
                "close_all_positions",
                {
                    "session_id": "s1",
                    "idempotency_key": "k-bulk-close",
                    "confirm": True,
                },
            )
            return cast(dict[str, object], result.data)

    payload = asyncio.run(call())
    assert "action" in payload
    assert "requested" in payload
    assert "succeeded" in payload
    assert "failed" in payload
    assert "items" in payload
    assert payload["requested"] == 1
    assert payload["succeeded"] == 1
    assert payload["failed"] == 0
    items = cast(list[dict[str, object]], payload["items"])
    assert len(items) == 1
    assert items[0]["status"] == "executed"


def test_close_all_by_symbol_wildcard_resolves_broker_symbol_casing(
    tmp_path: Path,
) -> None:
    server, backend, session_store, _ = _build_server(
        tmp_path,
        allowed_symbols=("*",),
    )
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )
    backend.symbols.append(FakeMT5Symbol(name="Boom 1000 Index", path="Synthetic"))
    backend.ticks["Boom 1000 Index"] = FakeMT5Tick(
        bid=14057.38,
        ask=14058.51,
        last=14058.00,
        volume=10,
        time=1_700_000_000,
    )
    backend.positions.append(
        FakeMT5Position(
            ticket=1002,
            symbol="Boom 1000 Index",
            volume=0.2,
            type=0,
            price_open=14058.51,
            profit=5.0,
            price_current=14058.51,
        )
    )

    async def call() -> dict[str, object]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            result = await client.call_tool(
                "close_all_by_symbol",
                {
                    "session_id": "s1",
                    "idempotency_key": "k-bulk-boom-close",
                    "symbol": "boom 1000 index",
                    "confirm": True,
                },
            )
            return cast(dict[str, object], result.data)

    payload = asyncio.run(call())

    assert payload["requested"] == 1
    assert payload["succeeded"] == 1
    items = cast(list[dict[str, object]], payload["items"])
    assert items[0]["symbol"] == "Boom 1000 Index"


def test_cancel_all_pending_by_symbol_wildcard_resolves_broker_symbol_casing(
    tmp_path: Path,
) -> None:
    server, backend, session_store, _ = _build_server(
        tmp_path,
        allowed_symbols=("*",),
    )
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )
    backend.symbols.append(FakeMT5Symbol(name="Boom 1000 Index", path="Synthetic"))
    backend.orders.append(
        FakeMT5Order(
            ticket=2002,
            symbol="Boom 1000 Index",
            volume_initial=0.2,
            price_open=14000.0,
            state=1,
            type=2,
        )
    )

    async def call() -> dict[str, object]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            result = await client.call_tool(
                "cancel_all_pending_by_symbol",
                {
                    "session_id": "s1",
                    "idempotency_key": "k-bulk-boom-cancel",
                    "symbol": "boom 1000 index",
                    "confirm": True,
                },
            )
            return cast(dict[str, object], result.data)

    payload = asyncio.run(call())

    assert payload["requested"] == 1
    assert payload["succeeded"] == 1
    items = cast(list[dict[str, object]], payload["items"])
    assert items[0]["symbol"] == "Boom 1000 Index"


# --- WU10-T13: close_all_profitable only includes profit>0 positions ---


def test_close_all_profitable_filters_correctly(tmp_path: Path) -> None:
    server, backend, session_store, _ = _build_server(tmp_path)
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )
    # Add a losing position alongside the default profitable one
    backend.positions.append(
        FakeMT5Position(
            ticket=1002,
            symbol="EURUSD",
            volume=0.1,
            type=0,
            price_open=1.15,
            profit=-10.0,
        )
    )

    async def call() -> dict[str, object]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            result = await client.call_tool(
                "close_all_profitable",
                {
                    "session_id": "s1",
                    "idempotency_key": "k-profitable",
                    "confirm": True,
                },
            )
            return cast(dict[str, object], result.data)

    payload = asyncio.run(call())
    # Only the profitable position (ticket=1001, profit=25.0) should be in requested
    assert payload["requested"] == 1
    items = cast(list[dict[str, object]], payload["items"])
    assert all(i["ticket"] != 1002 for i in items), "Losing position should not appear"


# --- WU10-T14: list_positions includes enriched snapshot fields ---


def test_list_positions_returns_enriched_snapshot_fields(tmp_path: Path) -> None:
    server, _, _, _ = _build_server(tmp_path)

    async def call() -> list[dict[str, object]]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            result = await client.call_tool("list_positions", {})
            return cast(list[dict[str, object]], result.data)

    positions = asyncio.run(call())
    assert len(positions) >= 1
    pos = positions[0]
    for field in ("sl", "tp", "price_current", "swap", "commission", "time", "magic", "comment"):
        assert field in pos, f"Enriched field {field!r} missing from list_positions response"
    # Original fields must still be present
    for field in ("ticket", "symbol", "volume", "profit", "account_mode"):
        assert field in pos, f"Original field {field!r} missing"


# --- WU10-T15: acknowledge_real_account with env-var pre-auth (no explicit actor) ---


def test_acknowledge_real_account_env_var_preauth(tmp_path: Path) -> None:
    # real_account_consent_env=True → trading allowed without session ack
    server, _, session_store, _ = _build_server(
        tmp_path, real_account_consent_env=True
    )
    # NO explicit session ack

    async def call() -> dict[str, object]:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            result = await client.call_tool(
                "place_market_order",
                {
                    "session_id": "s-env-auth",
                    "idempotency_key": "k-env-auth",
                    "symbol": "EURUSD",
                    "side": "buy",
                    "volume": "0.1",
                },
            )
            return cast(dict[str, object], result.data)

    payload = asyncio.run(call())
    # Should succeed — env-var consent bypasses per-session ack
    assert int(payload["order"]) > 0


# --- WU10-T16: AuditStore event sequence: executed + duplicate + rejected ---


def test_audit_event_sequence(tmp_path: Path) -> None:
    server, _, session_store, audit_store = _build_server(tmp_path)
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )

    async def workflow() -> None:
        from fastmcp.client import Client

        async with Client(server) as client:  # type: ignore[arg-type]
            params = {
                "session_id": "s1",
                "idempotency_key": "k-audit",
                "symbol": "EURUSD",
                "side": "buy",
                "volume": "0.1",
            }
            # First call → executed
            await client.call_tool("place_market_order", params)
            # Second call → duplicate
            await client.call_tool("place_market_order", params)

    asyncio.run(workflow())

    events = audit_store.fetch_all()
    decisions = [e["decision"] for e in events]
    assert "executed" in decisions
    assert "duplicate" in decisions


# ---------------------------------------------------------------------------
# Error-path contract tests — AT-1-d, AT-1-e, AT-5-c, AT-3-b
#
# All 4 reveal that the existing tool layer already surfaces validation
# and service errors as clean ToolError exceptions (NOT unhandled tracebacks).
# These tests pin that contract through the tool surface.
# ---------------------------------------------------------------------------


# --- AT-1-d: place_market_order with an invalid/unknown symbol ---


def test_place_market_order_invalid_symbol_returns_clean_rejection(
    tmp_path: Path,
) -> None:
    """AT-1-d: unknown symbol raises a clean ToolError, no executed audit event."""
    import pytest
    from fastmcp.client import Client

    server, _, session_store, audit_store = _build_server(tmp_path)
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )

    async def call() -> str:
        async with Client(server) as client:  # type: ignore[arg-type]
            with pytest.raises(Exception) as exc_info:
                await client.call_tool(
                    "place_market_order",
                    {
                        "session_id": "s1",
                        "idempotency_key": "k-bad-sym",
                        "symbol": "INVALID_SYM",
                        "side": "buy",
                        "volume": "0.1",
                    },
                )
            return str(exc_info.value)

    err_msg = asyncio.run(call())
    # Clean rejection — must mention the symbol, not a raw traceback
    assert "INVALID_SYM" in err_msg or "symbol" in err_msg.lower()
    # No executed audit event recorded
    events = audit_store.fetch_all()
    executed = [e for e in events if e["decision"] == "executed"]
    assert len(executed) == 0


# --- AT-1-e: place_market_order with zero volume ---


def test_place_market_order_zero_volume_returns_clean_rejection(
    tmp_path: Path,
) -> None:
    """AT-1-e: volume=0 raises a clean ToolError before MT5 is called."""
    import pytest
    from fastmcp.client import Client

    server, _, session_store, audit_store = _build_server(tmp_path)
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )

    async def call() -> str:
        async with Client(server) as client:  # type: ignore[arg-type]
            with pytest.raises(Exception) as exc_info:
                await client.call_tool(
                    "place_market_order",
                    {
                        "session_id": "s1",
                        "idempotency_key": "k-zero-vol",
                        "symbol": "EURUSD",
                        "side": "buy",
                        "volume": "0",
                    },
                )
            return str(exc_info.value)

    err_msg = asyncio.run(call())
    # Clean rejection — must mention volume
    assert "volume" in err_msg.lower()
    # No executed audit event recorded
    events = audit_store.fetch_all()
    executed = [e for e in events if e["decision"] == "executed"]
    assert len(executed) == 0


# --- AT-5-c: close_position with negative volume ---


def test_close_position_negative_volume_returns_clean_rejection(
    tmp_path: Path,
) -> None:
    """AT-5-c: volume=-0.1 raises a clean ToolError before MT5 is called."""
    import pytest
    from fastmcp.client import Client

    server, _, session_store, audit_store = _build_server(tmp_path)
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )

    async def call() -> str:
        async with Client(server) as client:  # type: ignore[arg-type]
            with pytest.raises(Exception) as exc_info:
                await client.call_tool(
                    "close_position",
                    {
                        "session_id": "s1",
                        "idempotency_key": "k-neg-vol",
                        "symbol": "EURUSD",
                        "ticket": 1001,
                        "volume": "-0.1",
                    },
                )
            return str(exc_info.value)

    err_msg = asyncio.run(call())
    # Clean rejection — must mention volume
    assert "volume" in err_msg.lower()
    # No executed audit event recorded
    events = audit_store.fetch_all()
    executed = [e for e in events if e["decision"] == "executed"]
    assert len(executed) == 0


# --- AT-3-b: modify_position with a nonexistent ticket ---


def test_modify_position_nonexistent_ticket_returns_clean_rejection(
    tmp_path: Path,
) -> None:
    """AT-3-b: nonexistent ticket raises a clean ToolError, no executed audit event."""
    import pytest
    from fastmcp.client import Client

    server, _, session_store, audit_store = _build_server(tmp_path)
    session_store.acknowledge_real_account(
        session_id="s1", actor="user@test.com", account_login=123456
    )

    async def call() -> str:
        async with Client(server) as client:  # type: ignore[arg-type]
            with pytest.raises(Exception) as exc_info:
                await client.call_tool(
                    "modify_position",
                    {
                        "session_id": "s1",
                        "idempotency_key": "k-no-ticket",
                        "symbol": "EURUSD",
                        "ticket": 99999,
                        "stop_loss": 1.08,
                        "take_profit": 1.12,
                    },
                )
            return str(exc_info.value)

    err_msg = asyncio.run(call())
    # Clean rejection — must mention ticket or position not found
    assert "ticket" in err_msg.lower() or "position" in err_msg.lower()
    # No executed audit event recorded
    events = audit_store.fetch_all()
    executed = [e for e in events if e["decision"] == "executed"]
    assert len(executed) == 0
