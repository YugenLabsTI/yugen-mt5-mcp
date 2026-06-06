"""Unit tests for trading result models — WU2 (TDD red-first)."""

from __future__ import annotations

from decimal import Decimal

from yugen_mt5_mcp.market_data import to_payload
from yugen_mt5_mcp.trading import BulkItemResult, BulkTradeResult, ExecutedTrade

# ---------------------------------------------------------------------------
# WU2-T1: Enriched ExecutedTrade — all seven AT-9-a required payload keys
# ---------------------------------------------------------------------------


def _base_trade(**overrides: object) -> ExecutedTrade:
    base: dict[str, object] = dict(
        idempotency_key="k1",
        action="open",
        symbol="EURUSD",
        requested_volume=Decimal("0.10"),
        retcode=10009,
        order=9001,
        deal=9101,
        executed_volume=0.10,
        executed_price=1.102,
        comment="done",
    )
    base.update(overrides)
    return ExecutedTrade(**base)  # type: ignore[arg-type]


def test_executed_trade_new_fields_have_defaults() -> None:
    trade = _base_trade()
    assert trade.applied_sl is None
    assert trade.applied_tp is None
    assert trade.deviation is None
    assert trade.position is None
    assert trade.dry_run is False


def test_executed_trade_new_fields_can_be_set() -> None:
    trade = _base_trade(
        applied_sl=1.090, applied_tp=1.120, deviation=3, position=1001, dry_run=True
    )
    assert trade.applied_sl == 1.090
    assert trade.applied_tp == 1.120
    assert trade.deviation == 3
    assert trade.position == 1001
    assert trade.dry_run is True


def test_executed_trade_to_payload_contains_all_seven_required_keys() -> None:
    trade = _base_trade(applied_sl=1.090, applied_tp=1.120, deviation=3)
    payload = to_payload(trade)
    assert isinstance(payload, dict)
    for key in (
        "executed_price", "executed_volume", "order", "deal",
        "applied_sl", "applied_tp", "deviation",
    ):
        assert key in payload, f"missing key: {key}"


def test_executed_trade_to_payload_decimal_requested_volume_is_string() -> None:
    trade = _base_trade()
    payload = to_payload(trade)
    assert isinstance(payload, dict)
    assert payload["requested_volume"] == "0.10"


def test_executed_trade_is_back_compat_without_new_fields() -> None:
    """Existing callers building ExecutedTrade without new fields must not break."""
    trade = ExecutedTrade(
        idempotency_key="k2",
        action="close",
        symbol="EURUSD",
        requested_volume=Decimal("0.20"),
        retcode=10009,
        order=9002,
        deal=9102,
        executed_volume=0.20,
        executed_price=1.101,
        comment="done",
    )
    assert trade.dry_run is False
    assert trade.applied_sl is None


# ---------------------------------------------------------------------------
# WU2-T2: BulkItemResult and BulkTradeResult frozen dataclasses
# ---------------------------------------------------------------------------


def test_bulk_item_result_executed_status() -> None:
    trade = _base_trade()
    item = BulkItemResult(ticket=1001, symbol="EURUSD", status="executed", executed=trade)
    assert item.ticket == 1001
    assert item.symbol == "EURUSD"
    assert item.status == "executed"
    assert item.executed is trade
    assert item.error is None


def test_bulk_item_result_failed_status() -> None:
    item = BulkItemResult(ticket=1002, symbol="EURUSD", status="failed", error="timeout")
    assert item.status == "failed"
    assert item.executed is None
    assert item.error == "timeout"


def test_bulk_item_result_skipped_status() -> None:
    item = BulkItemResult(ticket=1003, symbol="EURUSD", status="skipped")
    assert item.status == "skipped"
    assert item.executed is None
    assert item.error is None


def test_bulk_item_result_is_frozen() -> None:
    item = BulkItemResult(ticket=1001, symbol="EURUSD", status="executed")
    try:
        item.ticket = 9999  # type: ignore[misc]
        raise AssertionError("should have raised FrozenInstanceError")
    except Exception as exc:
        assert "frozen" in str(exc).lower() or "cannot assign" in str(exc).lower()


def test_bulk_trade_result_shape() -> None:
    item = BulkItemResult(ticket=1001, symbol="EURUSD", status="executed", executed=_base_trade())
    result = BulkTradeResult(
        action="close_all",
        requested=1,
        succeeded=1,
        failed=0,
        mode="best_effort",
        items=[item],
    )
    assert result.requested == 1
    assert result.succeeded == 1
    assert result.failed == 0
    assert result.mode == "best_effort"
    assert len(result.items) == 1


def test_bulk_trade_result_is_frozen() -> None:
    result = BulkTradeResult(
        action="close_all", requested=0, succeeded=0, failed=0, mode="best_effort", items=[]
    )
    try:
        result.requested = 99  # type: ignore[misc]
        raise AssertionError("should have raised FrozenInstanceError")
    except Exception as exc:
        assert "frozen" in str(exc).lower() or "cannot assign" in str(exc).lower()


def test_bulk_trade_result_to_payload_serializes_nested_items() -> None:
    trade = _base_trade()
    item = BulkItemResult(ticket=1001, symbol="EURUSD", status="executed", executed=trade)
    result = BulkTradeResult(
        action="close_all", requested=1, succeeded=1, failed=0, mode="best_effort", items=[item]
    )
    payload = to_payload(result)
    assert isinstance(payload, dict)
    assert payload["action"] == "close_all"
    assert payload["requested"] == 1
    items_payload = payload["items"]
    assert isinstance(items_payload, list)
    assert len(items_payload) == 1
    item_payload = items_payload[0]
    assert isinstance(item_payload, dict)
    assert item_payload["status"] == "executed"
    assert item_payload["ticket"] == 1001
    assert isinstance(item_payload["executed"], dict)
    assert item_payload["executed"]["requested_volume"] == "0.10"
