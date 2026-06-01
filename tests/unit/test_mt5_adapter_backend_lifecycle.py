from __future__ import annotations

import sys
from types import ModuleType

import pytest

from tests.fakes.fake_mt5 import FakeMT5Backend, FakeMT5Order, FakeMT5Position
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
