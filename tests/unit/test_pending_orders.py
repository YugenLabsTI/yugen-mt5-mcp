"""WU4 — Pending order service methods (TDD: write all RED tests first)."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from tests.fakes.fake_mt5 import FakeMT5Backend
from yugen_mt5_mcp.audit import AuditStore
from yugen_mt5_mcp.config import AppConfig, RiskConfig
from yugen_mt5_mcp.mt5_adapter import MT5Adapter
from yugen_mt5_mcp.risk import RiskPolicy, RiskPolicyError
from yugen_mt5_mcp.session import SessionRiskStore
from yugen_mt5_mcp.trading import TradingError, TradingService


def build_trading_service(
    tmp_path: Path,
    *,
    backend: FakeMT5Backend | None = None,
    risk_config: RiskConfig | None = None,
) -> tuple[TradingService, FakeMT5Backend, SessionRiskStore, AuditStore]:
    fake_backend = backend or FakeMT5Backend()
    adapter = MT5Adapter(backend=fake_backend)
    audit_store = AuditStore(tmp_path / "audit.sqlite3")
    session_store = SessionRiskStore()
    policy = RiskPolicy(
        config=AppConfig(
            risk=risk_config
            or RiskConfig(
                allowed_symbols=("EURUSD",),
                allowed_account_modes=("hedging", "netting"),
                max_order_volume=Decimal("1.00"),
                max_symbol_exposure=Decimal("2.00"),
                allow_live_trading=True,
                allow_real_accounts=True,
            )
        ),
        session_store=session_store,
        audit_store=audit_store,
    )
    service = TradingService(adapter=adapter, risk_policy=policy, audit_store=audit_store)
    return service, fake_backend, session_store, audit_store


# ---------------------------------------------------------------------------
# WU4-T1: FakeMT5Backend handles TRADE_ACTION_PENDING → inserts into self.orders
# ---------------------------------------------------------------------------


def test_fake_mt5_pending_action_inserts_order() -> None:
    backend = FakeMT5Backend()
    initial_count = len(backend.orders)

    result = backend.order_send(
        {
            "action": backend.TRADE_ACTION_PENDING,
            "symbol": "EURUSD",
            "volume": 0.1,
            "type": backend.ORDER_TYPE_BUY_LIMIT,
            "price": 1.09,
        }
    )

    assert result.retcode == backend.TRADE_RETCODE_DONE
    assert len(backend.orders) == initial_count + 1
    new_order = backend.orders[-1]
    assert new_order.symbol == "EURUSD"
    assert new_order.price_open == pytest.approx(1.09)


# ---------------------------------------------------------------------------
# WU4-T2: FakeMT5Backend handles TRADE_ACTION_REMOVE → removes from self.orders
# ---------------------------------------------------------------------------


def test_fake_mt5_remove_action_deletes_order() -> None:
    backend = FakeMT5Backend()
    # use the existing order ticket (2001) set up in __init__
    existing_ticket = backend.orders[0].ticket
    initial_count = len(backend.orders)

    result = backend.order_send(
        {
            "action": backend.TRADE_ACTION_REMOVE,
            "order": existing_ticket,
        }
    )

    assert result.retcode == backend.TRADE_RETCODE_DONE
    assert len(backend.orders) == initial_count - 1
    assert all(o.ticket != existing_ticket for o in backend.orders)


# ---------------------------------------------------------------------------
# WU4-T3: FakeMT5Backend handles TRADE_ACTION_MODIFY → updates order
# ---------------------------------------------------------------------------


def test_fake_mt5_modify_action_updates_order() -> None:
    backend = FakeMT5Backend()
    existing_ticket = backend.orders[0].ticket
    new_price = 1.08

    result = backend.order_send(
        {
            "action": backend.TRADE_ACTION_MODIFY,
            "order": existing_ticket,
            "price": new_price,
            "sl": 1.07,
            "tp": 1.10,
        }
    )

    assert result.retcode == backend.TRADE_RETCODE_DONE
    updated = next(o for o in backend.orders if o.ticket == existing_ticket)
    assert updated.price_open == pytest.approx(new_price)


# ---------------------------------------------------------------------------
# WU4-T4: TradingService.place_pending_order happy path (AT-2-a)
# ---------------------------------------------------------------------------


def test_place_pending_order_happy_path(tmp_path: Path) -> None:
    service, backend, _, _ = build_trading_service(tmp_path)

    executed = service.place_pending_order(
        session_id="session-1",
        idempotency_key="pending-1",
        symbol="EURUSD",
        order_type="buy_limit",
        volume=Decimal("0.10"),
        price=1.09,
        stop_loss=1.08,
        take_profit=1.11,
    )

    assert executed.order > 0
    assert executed.action == "place_pending"
    assert executed.symbol == "EURUSD"


# ---------------------------------------------------------------------------
# WU4-T5: TradingService.place_pending_order risk rejection (AT-2-b)
# ---------------------------------------------------------------------------


def test_place_pending_order_risk_rejection(tmp_path: Path) -> None:
    service, backend, _, _ = build_trading_service(
        tmp_path,
        risk_config=RiskConfig(
            allowed_symbols=("EURUSD",),
            allowed_account_modes=("hedging",),
            allow_live_trading=False,  # disabled
        ),
    )

    with pytest.raises((TradingError, RiskPolicyError)):
        service.place_pending_order(
            session_id="session-1",
            idempotency_key="pending-risk-fail",
            symbol="EURUSD",
            order_type="buy_limit",
            volume=Decimal("0.10"),
            price=1.09,
        )

    # No MT5 send should have been called
    # (order_check/send not called for risk-rejected path)
    send_calls = [r for r in backend.order_requests if r.get("action") == backend.TRADE_ACTION_PENDING]
    assert len(send_calls) == 0


# ---------------------------------------------------------------------------
# WU4-T6: TradingService.modify_pending_order happy path (AT-4-a)
# ---------------------------------------------------------------------------


def test_modify_pending_order_happy_path(tmp_path: Path) -> None:
    service, backend, _, _ = build_trading_service(tmp_path)
    existing_ticket = backend.orders[0].ticket

    executed = service.modify_pending_order(
        session_id="session-1",
        idempotency_key="mod-pending-1",
        ticket=existing_ticket,
        symbol="EURUSD",
        price=1.08,
        stop_loss=1.07,
        take_profit=1.10,
    )

    assert executed.order == existing_ticket
    assert executed.action == "modify"


# ---------------------------------------------------------------------------
# WU4-T7: TradingService.modify_pending_order on cancelled (non-existent) ticket (AT-4-b)
# ---------------------------------------------------------------------------


def test_modify_pending_order_nonexistent_ticket(tmp_path: Path) -> None:
    service, backend, _, _ = build_trading_service(tmp_path)

    with pytest.raises(TradingError, match="order ticket not found"):
        service.modify_pending_order(
            session_id="session-1",
            idempotency_key="mod-pending-fail",
            ticket=9999,
            symbol="EURUSD",
            price=1.08,
        )


# ---------------------------------------------------------------------------
# WU4-T8: TradingService.cancel_pending_order happy path (AT-6-a)
# ---------------------------------------------------------------------------


def test_cancel_pending_order_happy_path(tmp_path: Path) -> None:
    service, backend, _, audit_store = build_trading_service(tmp_path)
    existing_ticket = backend.orders[0].ticket

    executed = service.cancel_pending_order(
        session_id="session-1",
        idempotency_key="cancel-pending-1",
        ticket=existing_ticket,
        symbol="EURUSD",
    )

    assert executed.action == "cancel_pending"
    # Order removed from backend
    assert all(o.ticket != existing_ticket for o in backend.orders)
    # "executed" audit event present
    rows = audit_store.fetch_all()
    trade_rows = [r for r in rows if r["event_type"] == "trade.execute"]
    decisions = [r["decision"] for r in trade_rows]
    assert "executed" in decisions


# ---------------------------------------------------------------------------
# WU4-T9: TradingService.cancel_pending_order on already-filled (non-existent) ticket (AT-6-b)
# ---------------------------------------------------------------------------


def test_cancel_pending_order_already_filled(tmp_path: Path) -> None:
    service, backend, _, audit_store = build_trading_service(tmp_path)

    with pytest.raises(TradingError, match="order ticket not found"):
        service.cancel_pending_order(
            session_id="session-1",
            idempotency_key="cancel-filled",
            ticket=9999,
            symbol="EURUSD",
        )

    rows = audit_store.fetch_all()
    trade_executed_rows = [
        r for r in rows
        if r["event_type"] == "trade.execute" and r["decision"] == "executed"
    ]
    assert len(trade_executed_rows) == 0
