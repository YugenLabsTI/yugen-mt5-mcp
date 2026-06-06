"""Unit tests for enriched PositionSnapshot — WU3 (TDD red-first)."""

from __future__ import annotations

from datetime import UTC, datetime

from tests.fakes.fake_mt5 import FakeMT5Backend
from yugen_mt5_mcp.mt5_adapter import MT5Adapter

# ---------------------------------------------------------------------------
# WU3-T1: FakeMT5Backend list_positions includes new fields (PS-1-a)
# ---------------------------------------------------------------------------


def test_list_positions_snapshot_includes_new_enriched_fields() -> None:
    backend = FakeMT5Backend()
    # Verify the default FakeMT5 position carries all new fields
    adapter = MT5Adapter(backend=backend)

    positions = adapter.list_positions()

    assert len(positions) >= 1
    snap = positions[0]

    # New enriched fields
    assert hasattr(snap, "sl"), "missing field: sl"
    assert hasattr(snap, "tp"), "missing field: tp"
    assert hasattr(snap, "price_current"), "missing field: price_current"
    assert hasattr(snap, "swap"), "missing field: swap"
    assert hasattr(snap, "commission"), "missing field: commission"
    assert hasattr(snap, "time"), "missing field: time"
    assert hasattr(snap, "magic"), "missing field: magic"
    assert hasattr(snap, "comment"), "missing field: comment"


def test_list_positions_snapshot_field_types() -> None:
    backend = FakeMT5Backend()
    adapter = MT5Adapter(backend=backend)

    snap = adapter.list_positions()[0]

    assert isinstance(snap.sl, float)
    assert isinstance(snap.tp, float)
    assert isinstance(snap.price_current, float)
    assert isinstance(snap.swap, float)
    assert isinstance(snap.commission, float)
    assert isinstance(snap.time, datetime)
    assert isinstance(snap.magic, int)
    assert isinstance(snap.comment, str)


def test_fake_position_with_custom_sl_tp_values() -> None:
    backend = FakeMT5Backend()
    # Mutate the default position to set sl/tp
    backend.positions[0].sl = 1.090
    backend.positions[0].tp = 1.120
    adapter = MT5Adapter(backend=backend)

    snap = adapter.list_positions()[0]

    assert snap.sl == 1.090
    assert snap.tp == 1.120


# ---------------------------------------------------------------------------
# WU3-T2: Additive guard — existing fields unchanged (PS-1-b)
# ---------------------------------------------------------------------------


def test_list_positions_existing_fields_unchanged() -> None:
    """All previously-present keys must still exist with unchanged semantics."""
    backend = FakeMT5Backend()
    adapter = MT5Adapter(backend=backend)

    snap = adapter.list_positions("EURUSD")[0]

    # Pre-existing fields
    assert snap.ticket == 1001
    assert snap.symbol == "EURUSD"
    assert snap.volume == 0.2
    assert snap.order_type == 0
    assert snap.price_open == 1.095
    assert snap.profit == 25.0
    assert snap.account_mode == "hedging"


def test_list_positions_time_field_is_utc_aware() -> None:
    backend = FakeMT5Backend()
    adapter = MT5Adapter(backend=backend)

    snap = adapter.list_positions()[0]

    assert snap.time.tzinfo is not None
    assert snap.time.tzinfo == UTC
