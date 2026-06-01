from __future__ import annotations

import sys
from datetime import UTC, datetime
from types import ModuleType

import pytest

from tests.fakes.fake_mt5 import (
    FakeMT5Backend,
    FakeMT5Deal,
    FakeMT5HistoryOrder,
    FakeMT5Order,
    FakeMT5Position,
)
from yugen_mt5_mcp.mt5_adapter import MT5Adapter, MT5AdapterError, load_default_backend


class ImportableFakeMT5Backend(FakeMT5Backend, ModuleType):
    def __init__(self) -> None:
        ModuleType.__init__(self, "MetaTrader5")
        FakeMT5Backend.__init__(self)


class StrictOptionalSymbolBackend(FakeMT5Backend):
    def __init__(self) -> None:
        super().__init__()
        self.position_call_kwargs: list[dict[str, object]] = []
        self.order_call_kwargs: list[dict[str, object]] = []
        self.history_deal_call_kwargs: list[dict[str, object]] = []
        self.history_order_call_kwargs: list[dict[str, object]] = []

    def positions_get(self, **kwargs: object) -> list[FakeMT5Position]:
        self.position_call_kwargs.append(dict(kwargs))
        if kwargs.get("symbol") is None and "symbol" in kwargs:
            self._last_error = (-2, 'Invalid "symbol" argument')
            return None  # type: ignore[return-value]
        symbol = kwargs.get("symbol")
        if symbol is None:
            return list(self.positions)
        return [item for item in self.positions if item.symbol == symbol]

    def orders_get(self, **kwargs: object) -> list[FakeMT5Order]:
        self.order_call_kwargs.append(dict(kwargs))
        if kwargs.get("symbol") is None and "symbol" in kwargs:
            self._last_error = (-2, 'Invalid "symbol" argument')
            return None  # type: ignore[return-value]
        symbol = kwargs.get("symbol")
        if symbol is None:
            return list(self.orders)
        return [item for item in self.orders if item.symbol == symbol]

    def history_deals_get(
        self,
        date_from: datetime,
        date_to: datetime,
        **kwargs: object,
    ) -> list[FakeMT5Deal]:
        del date_from, date_to
        self.history_deal_call_kwargs.append(dict(kwargs))
        if kwargs.get("group") is None and "group" in kwargs:
            self._last_error = (-2, 'Invalid "group" argument')
            return None  # type: ignore[return-value]
        group = kwargs.get("group")
        if group is None:
            return list(self.deals)
        return [item for item in self.deals if item.symbol == group]

    def history_orders_get(
        self,
        date_from: datetime,
        date_to: datetime,
        **kwargs: object,
    ) -> list[FakeMT5HistoryOrder]:
        del date_from, date_to
        self.history_order_call_kwargs.append(dict(kwargs))
        if kwargs.get("group") is None and "group" in kwargs:
            self._last_error = (-2, 'Invalid "group" argument')
            return None  # type: ignore[return-value]
        group = kwargs.get("group")
        if group is None:
            return list(self.history_orders)
        return [item for item in self.history_orders if item.symbol == group]


def test_default_backend_initializes_imported_metatrader_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = ImportableFakeMT5Backend()
    monkeypatch.setitem(sys.modules, "MetaTrader5", backend)

    loaded = load_default_backend()

    assert loaded is backend
    assert backend.initialized is True


def test_default_backend_reports_initialization_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = ImportableFakeMT5Backend()
    backend.initialize = lambda: False  # type: ignore[method-assign]
    backend._last_error = (-10004, "No IPC connection")
    monkeypatch.setitem(sys.modules, "MetaTrader5", backend)

    with pytest.raises(MT5AdapterError, match="initialize failed"):
        load_default_backend()


def test_optional_position_and_order_symbol_filter_is_omitted_when_absent() -> None:
    backend = StrictOptionalSymbolBackend()
    adapter = MT5Adapter(backend=backend)

    positions = adapter.list_positions()
    orders = adapter.list_orders()

    assert len(positions) == 1
    assert len(orders) == 1
    assert backend.position_call_kwargs == [{}]
    assert backend.order_call_kwargs == [{}]


def test_optional_position_and_order_symbol_filter_is_sent_when_present() -> None:
    backend = StrictOptionalSymbolBackend()
    adapter = MT5Adapter(backend=backend)

    adapter.list_positions("EURUSD")
    adapter.list_orders("EURUSD")

    assert backend.position_call_kwargs == [{"symbol": "EURUSD"}]
    assert backend.order_call_kwargs == [{"symbol": "EURUSD"}]


def test_optional_history_group_filter_is_omitted_when_absent() -> None:
    backend = StrictOptionalSymbolBackend()
    adapter = MT5Adapter(backend=backend)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 2, tzinfo=UTC)

    deals = adapter.list_history_deals(start, end)
    orders = adapter.list_history_orders(start, end)

    assert len(deals) == 1
    assert len(orders) == 1
    assert backend.history_deal_call_kwargs == [{}]
    assert backend.history_order_call_kwargs == [{}]


def test_optional_history_group_filter_is_sent_when_present() -> None:
    backend = StrictOptionalSymbolBackend()
    adapter = MT5Adapter(backend=backend)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 2, tzinfo=UTC)

    adapter.list_history_deals(start, end, "EURUSD")
    adapter.list_history_orders(start, end, "EURUSD")

    assert backend.history_deal_call_kwargs == [{"group": "EURUSD"}]
    assert backend.history_order_call_kwargs == [{"group": "EURUSD"}]
