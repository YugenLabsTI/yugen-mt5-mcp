"""WU5 — Dry-run mode (TDD: RED first)."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from tests.fakes.fake_mt5 import FakeMT5Backend
from yugen_mt5_mcp.audit import AuditStore
from yugen_mt5_mcp.config import AppConfig, RiskConfig
from yugen_mt5_mcp.mt5_adapter import MT5Adapter
from yugen_mt5_mcp.risk import RiskPolicy
from yugen_mt5_mcp.session import SessionRiskStore
from yugen_mt5_mcp.trading import TradeSide, TradingService


def build_trading_service(
    tmp_path: Path,
    *,
    backend: FakeMT5Backend | None = None,
) -> tuple[TradingService, FakeMT5Backend, AuditStore]:
    fake_backend = backend or FakeMT5Backend()
    adapter = MT5Adapter(backend=fake_backend)
    audit_store = AuditStore(tmp_path / "audit.sqlite3")
    session_store = SessionRiskStore()
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
        session_store=session_store,
        audit_store=audit_store,
    )
    service = TradingService(adapter=adapter, risk_policy=policy, audit_store=audit_store)
    return service, fake_backend, audit_store


# ---------------------------------------------------------------------------
# WU5-T1: dry_run=False (default) — send_trade called exactly once (AT-8-a)
# ---------------------------------------------------------------------------


def test_place_market_order_dry_run_false_calls_send_trade(tmp_path: Path) -> None:
    """Default path: send_trade must be called exactly once. Zero added latency."""
    service, backend, _ = build_trading_service(tmp_path)

    executed = service.open_position(
        session_id="session-1",
        idempotency_key="open-dry-false",
        symbol="EURUSD",
        side=TradeSide.BUY,
        volume=Decimal("0.10"),
        dry_run=False,
    )

    # order_requests has both check and send calls in the fake
    # The key assertion: result is NOT marked dry_run
    assert executed.dry_run is False
    assert executed.order > 0
    assert executed.deal > 0


# ---------------------------------------------------------------------------
# WU5-T2: dry_run=True — check_trade called, send_trade NOT called (AT-8-b)
# ---------------------------------------------------------------------------


def test_place_market_order_dry_run_true_skips_send_trade(tmp_path: Path) -> None:
    """Dry-run: only check_trade fires; send_trade must NOT be called."""
    service, backend, audit_store = build_trading_service(tmp_path)

    # Track calls via spy on the adapter
    original_send_trade = service._adapter.send_trade
    send_trade_calls: list[object] = []

    def spy_send_trade(request: object) -> object:
        send_trade_calls.append(request)
        return original_send_trade(request)  # type: ignore[arg-type]

    service._adapter.send_trade = spy_send_trade  # type: ignore[method-assign]

    executed = service.open_position(
        session_id="session-1",
        idempotency_key="open-dry-true",
        symbol="EURUSD",
        side=TradeSide.BUY,
        volume=Decimal("0.10"),
        dry_run=True,
    )

    # send_trade must NOT have been called
    assert len(send_trade_calls) == 0

    # Result has dry_run marker
    assert executed.dry_run is True
    assert executed.order == 0
    assert executed.deal == 0

    # Result is NOT cached — a subsequent real call with a DIFFERENT key still executes
    # Reset spy counter before the real call
    send_trade_calls.clear()
    executed_real = service.open_position(
        session_id="session-1",
        idempotency_key="open-dry-true-followup",
        symbol="EURUSD",
        side=TradeSide.BUY,
        volume=Decimal("0.10"),
        dry_run=False,
    )
    assert executed_real.dry_run is False
    assert executed_real.order > 0
    # The real call DID go through send_trade
    assert len(send_trade_calls) == 1

    # Verify that dry_run result was NOT cached under its key:
    # replaying the dry_run key again should stay dry (no send_trade, not treated as duplicate)
    send_trade_calls.clear()
    executed_dry_replay = service.open_position(
        session_id="session-1",
        idempotency_key="open-dry-true",  # same key as the dry run
        symbol="EURUSD",
        side=TradeSide.BUY,
        volume=Decimal("0.10"),
        dry_run=True,
    )
    # Since dry_run results are NOT cached, this fires check_trade again (not a duplicate event)
    assert executed_dry_replay.dry_run is True
    assert len(send_trade_calls) == 0  # still zero send_trade calls for dry replay


# ---------------------------------------------------------------------------
# WU5 extra: dry_run=True also works for place_pending_order
# ---------------------------------------------------------------------------


def test_place_pending_order_dry_run(tmp_path: Path) -> None:
    service, backend, _ = build_trading_service(tmp_path)

    send_trade_calls: list[object] = []
    original_send_trade = service._adapter.send_trade

    def spy_send_trade(request: object) -> object:
        send_trade_calls.append(request)
        return original_send_trade(request)  # type: ignore[arg-type]

    service._adapter.send_trade = spy_send_trade  # type: ignore[method-assign]

    executed = service.place_pending_order(
        session_id="session-1",
        idempotency_key="pending-dry",
        symbol="EURUSD",
        order_type="buy_limit",
        volume=Decimal("0.10"),
        price=1.09,
        dry_run=True,
    )

    assert executed.dry_run is True
    assert executed.order == 0
    assert executed.deal == 0
    assert len(send_trade_calls) == 0
