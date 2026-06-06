from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from tests.fakes.fake_mt5 import FakeMT5Backend
from yugen_mt5_mcp.audit import AuditStore
from yugen_mt5_mcp.config import AppConfig, RiskConfig
from yugen_mt5_mcp.mt5_adapter import MT5Adapter
from yugen_mt5_mcp.risk import RiskPolicy
from yugen_mt5_mcp.session import SessionRiskStore
from yugen_mt5_mcp.trading import TradeSide, TradingError, TradingService


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


def test_hedging_partial_close_targets_ticket_and_is_idempotent(tmp_path: Path) -> None:
    service, backend, _, _ = build_trading_service(tmp_path)

    executed = service.close_position(
        session_id="session-1",
        idempotency_key="close-hedging-1",
        symbol="EURUSD",
        ticket=1001,
        volume=Decimal("0.10"),
    )
    duplicate = service.close_position(
        session_id="session-1",
        idempotency_key="close-hedging-1",
        symbol="EURUSD",
        ticket=1001,
        volume=Decimal("0.10"),
    )

    assert executed.executed_volume == pytest.approx(0.10)
    assert duplicate.duplicate is True
    assert backend.positions[0].volume == pytest.approx(0.10)
    assert len(backend.order_requests) == 2


def test_close_above_max_order_volume_succeeds_end_to_end(tmp_path: Path) -> None:
    """A full close of a position larger than max_order_volume must succeed.

    Regression for the manual-QA bug: closing 19 lots with the cap at 5 was
    wrongly rejected. The cap applies to entries only, so a large close goes
    through close_position in one order.
    """
    service, backend, _, _ = build_trading_service(
        tmp_path,
        risk_config=RiskConfig(
            allowed_symbols=("EURUSD",),
            allowed_account_modes=("hedging", "netting"),
            max_order_volume=Decimal("0.10"),
            max_symbol_exposure=Decimal("2.00"),
            allow_live_trading=True,
            allow_real_accounts=True,
        ),
    )

    # The seeded hedging position (ticket 1001) holds 0.20 lots — twice the cap.
    executed = service.close_position(
        session_id="session-1",
        idempotency_key="close-above-cap",
        symbol="EURUSD",
        ticket=1001,
        volume=Decimal("0.20"),
    )

    assert executed.executed_volume == pytest.approx(0.20)
    # A full close removes the position entirely from the book.
    assert all(position.ticket != 1001 for position in backend.positions)


def test_netting_close_rejects_ticket_mismatch(tmp_path: Path) -> None:
    backend = FakeMT5Backend()
    backend.account.margin_mode = backend.ACCOUNT_MARGIN_MODE_RETAIL_NETTING
    service, _, _, _ = build_trading_service(tmp_path, backend=backend)

    with pytest.raises(TradingError, match="ticket does not match"):
        service.close_position(
            session_id="session-1",
            idempotency_key="close-netting-bad-ticket",
            symbol="EURUSD",
            ticket=9999,
            volume=Decimal("0.10"),
        )


def test_open_and_modify_position_verify_retcode(tmp_path: Path) -> None:
    service, backend, _, _ = build_trading_service(tmp_path)

    opened = service.open_position(
        session_id="session-1",
        idempotency_key="open-1",
        symbol="EURUSD",
        side=TradeSide.BUY,
        volume=Decimal("0.10"),
        stop_loss=1.0900,
        take_profit=1.1200,
    )
    modified = service.modify_position_levels(
        session_id="session-1",
        idempotency_key="modify-1",
        symbol="EURUSD",
        ticket=1001,
        stop_loss=1.0910,
        take_profit=1.1210,
    )

    assert opened.retcode == backend.TRADE_RETCODE_DONE
    assert modified.retcode == backend.TRADE_RETCODE_DONE


def test_trade_send_failure_is_reported(tmp_path: Path) -> None:
    service, backend, _, audit_store = build_trading_service(tmp_path)
    backend.order_send_result.retcode = backend.TRADE_RETCODE_REJECT
    backend.order_send_result.comment = "broker reject"

    with pytest.raises(TradingError, match="retcode"):
        service.open_position(
            session_id="session-1",
            idempotency_key="open-reject",
            symbol="EURUSD",
            side=TradeSide.BUY,
            volume=Decimal("0.10"),
        )

    rows = audit_store.fetch_all()
    trade_rejection = rows[-1]
    payload = json.loads(trade_rejection["context_json"])
    assert trade_rejection["event_type"] == "trade.execute"
    assert trade_rejection["decision"] == "rejected"
    assert payload["operation"] == "order_send"
    assert payload["retcode"] == backend.TRADE_RETCODE_REJECT
