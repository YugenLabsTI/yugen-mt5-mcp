"""Regression: real MT5 order_check() reports success with retcode 0.

The MetaTrader5 Python API returns ``retcode=0`` / ``comment="Done"`` from
``order_check()`` when a request is valid (see official docs). The trading
service must treat that as success and proceed to ``order_send``; otherwise it
raises ``order_check failed with retcode 0: Done`` and the trade never reaches
the broker.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from tests.fakes.fake_mt5 import FakeMT5Backend, FakeMT5TradeResult
from yugen_mt5_mcp.audit import AuditStore
from yugen_mt5_mcp.config import AppConfig, RiskConfig
from yugen_mt5_mcp.mt5_adapter import MT5Adapter
from yugen_mt5_mcp.risk import RiskPolicy
from yugen_mt5_mcp.session import SessionRiskStore
from yugen_mt5_mcp.trading import TradeSide, TradingError, TradingService


def _build_service(
    tmp_path: Path, backend: FakeMT5Backend
) -> TradingService:
    adapter = MT5Adapter(backend=backend)
    audit_store = AuditStore(tmp_path / "audit.sqlite3")
    policy = RiskPolicy(
        config=AppConfig(
            risk=RiskConfig(
                allowed_symbols=("EURUSD",),
                allowed_account_modes=("hedging", "netting"),
                max_order_volume=Decimal("1.00"),
                max_symbol_exposure=Decimal("2.00"),
                allow_live_trading=True,
                allow_real_accounts=True,
            )
        ),
        session_store=SessionRiskStore(),
        audit_store=audit_store,
    )
    return TradingService(adapter=adapter, risk_policy=policy, audit_store=audit_store)


def test_order_check_retcode_zero_is_success_and_reaches_send_trade(
    tmp_path: Path,
) -> None:
    backend = FakeMT5Backend()
    # Model real MT5: order_check succeeds with retcode 0 / comment "Done".
    backend.order_check_result = FakeMT5TradeResult(retcode=0, comment="Done")
    service = _build_service(tmp_path, backend)

    send_trade_calls: list[object] = []
    original_send_trade = service._adapter.send_trade

    def spy_send_trade(request: object) -> object:
        send_trade_calls.append(request)
        return original_send_trade(request)  # type: ignore[arg-type]

    service._adapter.send_trade = spy_send_trade  # type: ignore[method-assign]

    executed = service.open_position(
        session_id="session-1",
        idempotency_key="open-check-zero",
        symbol="EURUSD",
        side=TradeSide.BUY,
        volume=Decimal("0.10"),
        dry_run=False,
    )

    assert len(send_trade_calls) == 1, "retcode 0 must not short-circuit before order_send"
    assert executed.order > 0
    assert executed.deal > 0
    assert executed.dry_run is False


def test_order_check_real_error_retcode_still_rejected(tmp_path: Path) -> None:
    """A genuine order_check error (e.g. 10019 no money) must still be rejected."""
    backend = FakeMT5Backend()
    backend.order_check_result = FakeMT5TradeResult(retcode=10019, comment="No money")
    service = _build_service(tmp_path, backend)

    with pytest.raises(TradingError, match="order_check failed with retcode 10019"):
        service.open_position(
            session_id="session-1",
            idempotency_key="open-check-nomoney",
            symbol="EURUSD",
            side=TradeSide.BUY,
            volume=Decimal("0.10"),
            dry_run=False,
        )
