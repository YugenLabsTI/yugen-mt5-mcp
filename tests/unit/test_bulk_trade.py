"""WU6 — BulkTradeService tests (TDD: all RED first, then GREEN)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from tests.fakes.fake_mt5 import FakeMT5Backend
from yugen_mt5_mcp.audit import AuditStore
from yugen_mt5_mcp.config import AppConfig, RiskConfig
from yugen_mt5_mcp.mt5_adapter import MT5Adapter
from yugen_mt5_mcp.risk import RiskPolicy
from yugen_mt5_mcp.session import SessionRiskStore
from yugen_mt5_mcp.trading import (
    BulkTradeResult,
    BulkTradeService,
    ExecutedTrade,
    TradingError,
    TradingService,
)


# ---------------------------------------------------------------------------
# Stub TradingService for isolation
# ---------------------------------------------------------------------------


@dataclass
class _StubTradingService:
    """Controllable stub — configure via calls_and_results list."""

    calls_and_results: list[ExecutedTrade | Exception]
    recorded_calls: list[dict[str, Any]]

    def __init__(self, results: list[ExecutedTrade | Exception]) -> None:
        self.calls_and_results = list(results)
        self.recorded_calls: list[dict[str, Any]] = []
        self._index = 0

    def close_position(self, **kwargs: Any) -> ExecutedTrade:
        self.recorded_calls.append({"method": "close_position", **kwargs})
        result = self._next_result()
        if isinstance(result, Exception):
            raise result
        return result

    def cancel_pending_order(self, **kwargs: Any) -> ExecutedTrade:
        self.recorded_calls.append({"method": "cancel_pending_order", **kwargs})
        result = self._next_result()
        if isinstance(result, Exception):
            raise result
        return result

    def _next_result(self) -> ExecutedTrade | Exception:
        item = self.calls_and_results[self._index]
        self._index += 1
        return item


def _make_executed(key: str = "k", ticket: int = 0) -> ExecutedTrade:
    return ExecutedTrade(
        idempotency_key=key,
        action="close",
        symbol="EURUSD",
        requested_volume=Decimal("0.1"),
        retcode=10009,
        order=ticket,
        deal=1,
        executed_volume=0.1,
        executed_price=1.1,
        comment="done",
    )


def _make_bulk_service(
    tmp_path: Path,
    stub: _StubTradingService,
    backend: FakeMT5Backend | None = None,
) -> BulkTradeService:
    fake_backend = backend or FakeMT5Backend()
    adapter = MT5Adapter(backend=fake_backend)
    audit_store = AuditStore(tmp_path / "audit.sqlite3")
    return BulkTradeService(
        trading_service=stub,  # type: ignore[arg-type]
        adapter=adapter,
        audit_store=audit_store,
    )


# ---------------------------------------------------------------------------
# WU6-T1: confirm=False → TradingError before any MT5 call (BK-2-a)
# ---------------------------------------------------------------------------


def test_bulk_close_all_requires_confirm(tmp_path: Path) -> None:
    stub = _StubTradingService([])
    service = _make_bulk_service(tmp_path, stub)

    with pytest.raises(TradingError, match="confirm=True"):
        service.close_all(
            session_id="s1",
            idempotency_key="bulk-1",
            confirm=False,
        )

    assert stub.recorded_calls == []


# ---------------------------------------------------------------------------
# WU6-T2: close_all best-effort, 3 positions, middle fails (BK-4-a)
# ---------------------------------------------------------------------------


def test_bulk_close_all_best_effort_partial_failure(tmp_path: Path) -> None:
    from tests.fakes.fake_mt5 import FakeMT5Position  # noqa: PLC0415

    backend = FakeMT5Backend()
    backend.positions = [
        FakeMT5Position(ticket=1001, symbol="EURUSD", volume=0.2, type=0, price_open=1.095, profit=10.0),
        FakeMT5Position(ticket=1002, symbol="EURUSD", volume=0.1, type=0, price_open=1.096, profit=5.0),
        FakeMT5Position(ticket=1003, symbol="EURUSD", volume=0.1, type=0, price_open=1.097, profit=-3.0),
    ]
    stub = _StubTradingService([
        _make_executed("bulk-1:1001", 1001),
        TradingError("mt5 error"),
        _make_executed("bulk-1:1003", 1003),
    ])
    service = _make_bulk_service(tmp_path, stub, backend)

    result = service.close_all(
        session_id="s1",
        idempotency_key="bulk-1",
        confirm=True,
    )

    assert isinstance(result, BulkTradeResult)
    assert result.requested == 3
    assert result.succeeded == 2
    assert result.failed == 1
    assert len(result.items) == 3
    statuses = [item.status for item in result.items]
    assert statuses[1] == "failed"
    assert result.items[1].error is not None


# ---------------------------------------------------------------------------
# WU6-T3: close_all fail-fast, first fails → items 2+3 skipped (BK-5-a)
# ---------------------------------------------------------------------------


def test_bulk_close_all_fail_fast_stops_on_first_failure(tmp_path: Path) -> None:
    from tests.fakes.fake_mt5 import FakeMT5Position  # noqa: PLC0415

    backend = FakeMT5Backend()
    backend.positions = [
        FakeMT5Position(ticket=1001, symbol="EURUSD", volume=0.2, type=0, price_open=1.095, profit=10.0),
        FakeMT5Position(ticket=1002, symbol="EURUSD", volume=0.1, type=0, price_open=1.096, profit=5.0),
        FakeMT5Position(ticket=1003, symbol="EURUSD", volume=0.1, type=0, price_open=1.097, profit=-3.0),
    ]
    stub = _StubTradingService([TradingError("first fails")])
    service = _make_bulk_service(tmp_path, stub, backend)

    result = service.close_all(
        session_id="s1",
        idempotency_key="bulk-fail",
        confirm=True,
        mode="fail_fast",
    )

    assert result.succeeded == 0
    assert result.failed == 1
    assert len(result.items) == 3
    assert result.items[0].status == "failed"
    assert result.items[1].status == "skipped"
    assert result.items[2].status == "skipped"
    assert result.mode == "fail_fast"


# ---------------------------------------------------------------------------
# WU6-T4: fail-fast, position 2 fails, position 1 remains executed (BK-5-b)
# ---------------------------------------------------------------------------


def test_bulk_close_all_fail_fast_prior_exec_not_rolled_back(tmp_path: Path) -> None:
    from tests.fakes.fake_mt5 import FakeMT5Position  # noqa: PLC0415

    backend = FakeMT5Backend()
    backend.positions = [
        FakeMT5Position(ticket=1001, symbol="EURUSD", volume=0.2, type=0, price_open=1.095, profit=10.0),
        FakeMT5Position(ticket=1002, symbol="EURUSD", volume=0.1, type=0, price_open=1.096, profit=5.0),
        FakeMT5Position(ticket=1003, symbol="EURUSD", volume=0.1, type=0, price_open=1.097, profit=-3.0),
    ]
    stub = _StubTradingService([
        _make_executed("bulk-1:1001", 1001),
        TradingError("second fails"),
    ])
    service = _make_bulk_service(tmp_path, stub, backend)

    result = service.close_all(
        session_id="s1",
        idempotency_key="bulk-1",
        confirm=True,
        mode="fail_fast",
    )

    assert result.items[0].status == "executed"
    assert result.items[1].status == "failed"
    assert result.items[2].status == "skipped"


# ---------------------------------------------------------------------------
# WU6-T5: empty position set → requested=0, items=[], no error (BK-6-a)
# ---------------------------------------------------------------------------


def test_bulk_close_all_empty_positions(tmp_path: Path) -> None:
    backend = FakeMT5Backend()
    backend.positions = []
    stub = _StubTradingService([])
    service = _make_bulk_service(tmp_path, stub, backend)

    result = service.close_all(
        session_id="s1",
        idempotency_key="bulk-empty",
        confirm=True,
    )

    assert result.requested == 0
    assert result.succeeded == 0
    assert result.failed == 0
    assert result.items == []


# ---------------------------------------------------------------------------
# WU6-T6: sub-key derivation — per-trade key = f"{bulk_key}:{ticket}" (BK-7-a)
# ---------------------------------------------------------------------------


def test_bulk_close_all_derives_per_trade_idempotency_sub_keys(tmp_path: Path) -> None:
    from tests.fakes.fake_mt5 import FakeMT5Position  # noqa: PLC0415

    backend = FakeMT5Backend()
    backend.positions = [
        FakeMT5Position(ticket=1001, symbol="EURUSD", volume=0.2, type=0, price_open=1.095, profit=10.0),
        FakeMT5Position(ticket=1002, symbol="EURUSD", volume=0.1, type=0, price_open=1.096, profit=5.0),
    ]
    stub = _StubTradingService([
        _make_executed("bulk-key:1001", 1001),
        _make_executed("bulk-key:1002", 1002),
    ])
    service = _make_bulk_service(tmp_path, stub, backend)

    service.close_all(
        session_id="s1",
        idempotency_key="bulk-key",
        confirm=True,
    )

    assert stub.recorded_calls[0]["idempotency_key"] == "bulk-key:1001"
    assert stub.recorded_calls[1]["idempotency_key"] == "bulk-key:1002"


# ---------------------------------------------------------------------------
# WU6-T7: cancel_all_pending best-effort shape (BulkTradeResult structure)
# ---------------------------------------------------------------------------


def test_bulk_cancel_all_pending_returns_bulk_trade_result(tmp_path: Path) -> None:
    backend = FakeMT5Backend()
    # backend.orders has 1 order by default (ticket=2001, symbol=EURUSD)
    stub = _StubTradingService([_make_executed("bulk-cancel:2001", 2001)])
    service = _make_bulk_service(tmp_path, stub, backend)

    result = service.cancel_all_pending(
        session_id="s1",
        idempotency_key="bulk-cancel",
        confirm=True,
    )

    assert isinstance(result, BulkTradeResult)
    assert result.action == "cancel_all_pending"
    assert result.requested == 1
    assert result.succeeded == 1
    assert result.failed == 0
    assert result.mode == "best_effort"


# ---------------------------------------------------------------------------
# WU6-T8: close_all_profitable filter — only profit>0 in requested (BK-9-a)
# ---------------------------------------------------------------------------


def test_bulk_close_all_profitable_filters_by_profit(tmp_path: Path) -> None:
    from tests.fakes.fake_mt5 import FakeMT5Position  # noqa: PLC0415

    backend = FakeMT5Backend()
    backend.positions = [
        FakeMT5Position(ticket=1001, symbol="EURUSD", volume=0.2, type=0, price_open=1.095, profit=50.0),
        FakeMT5Position(ticket=1002, symbol="EURUSD", volume=0.1, type=0, price_open=1.096, profit=-20.0),
    ]
    stub = _StubTradingService([_make_executed("bulk-1:1001", 1001)])
    service = _make_bulk_service(tmp_path, stub, backend)

    result = service.close_all(
        session_id="s1",
        idempotency_key="bulk-1",
        confirm=True,
        filter="profitable",
    )

    assert result.requested == 1
    assert result.items[0].ticket == 1001


# ---------------------------------------------------------------------------
# WU6-T9: close_all_losing filter — only profit<0 in requested
# ---------------------------------------------------------------------------


def test_bulk_close_all_losing_filters_by_profit(tmp_path: Path) -> None:
    from tests.fakes.fake_mt5 import FakeMT5Position  # noqa: PLC0415

    backend = FakeMT5Backend()
    backend.positions = [
        FakeMT5Position(ticket=1001, symbol="EURUSD", volume=0.2, type=0, price_open=1.095, profit=50.0),
        FakeMT5Position(ticket=1002, symbol="EURUSD", volume=0.1, type=0, price_open=1.096, profit=-20.0),
    ]
    stub = _StubTradingService([_make_executed("bulk-1:1002", 1002)])
    service = _make_bulk_service(tmp_path, stub, backend)

    result = service.close_all(
        session_id="s1",
        idempotency_key="bulk-1",
        confirm=True,
        filter="losing",
    )

    assert result.requested == 1
    assert result.items[0].ticket == 1002


# ---------------------------------------------------------------------------
# WU6-T10: per-trade audit events + single trade.bulk envelope audit (BK-8-a)
# ---------------------------------------------------------------------------


def test_bulk_close_all_emits_bulk_audit_envelope(tmp_path: Path) -> None:
    from tests.fakes.fake_mt5 import FakeMT5Position  # noqa: PLC0415

    backend = FakeMT5Backend()
    backend.positions = [
        FakeMT5Position(ticket=1001, symbol="EURUSD", volume=0.2, type=0, price_open=1.095, profit=10.0),
        FakeMT5Position(ticket=1002, symbol="EURUSD", volume=0.1, type=0, price_open=1.096, profit=5.0),
    ]
    stub = _StubTradingService([
        _make_executed("bulk-1:1001", 1001),
        _make_executed("bulk-1:1002", 1002),
    ])
    audit_store = AuditStore(tmp_path / "audit.sqlite3")
    adapter = MT5Adapter(backend=backend)
    service = BulkTradeService(
        trading_service=stub,  # type: ignore[arg-type]
        adapter=adapter,
        audit_store=audit_store,
    )

    service.close_all(
        session_id="s1",
        idempotency_key="bulk-1",
        confirm=True,
    )

    rows = audit_store.fetch_all()
    import json  # noqa: PLC0415

    bulk_rows = [r for r in rows if r["event_type"] == "trade.bulk"]
    assert len(bulk_rows) == 1
    ctx = json.loads(bulk_rows[0]["context_json"])
    assert ctx["succeeded"] == 2
    assert ctx["failed"] == 0
