from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast


@dataclass(slots=True)
class FakeMT5Symbol:
    name: str
    path: str = "Forex\\Major"
    visible: bool = True


@dataclass(slots=True)
class FakeMT5Tick:
    bid: float
    ask: float
    last: float
    time: int
    volume: int = 0


@dataclass(slots=True)
class FakeMT5Account:
    login: int
    server: str
    balance: float
    equity: float
    margin_free: float
    leverage: int
    currency: str
    company: str
    margin_mode: int
    trade_mode: int


@dataclass(slots=True)
class FakeMT5Position:
    ticket: int
    symbol: str
    volume: float
    type: int
    price_open: float
    profit: float


@dataclass(slots=True)
class FakeMT5Order:
    ticket: int
    symbol: str
    volume_initial: float
    price_open: float
    state: int
    type: int


@dataclass(slots=True)
class FakeMT5Deal:
    ticket: int
    order: int
    symbol: str
    volume: float
    price: float
    profit: float
    type: int
    entry: int
    time: int


@dataclass(slots=True)
class FakeMT5HistoryOrder:
    ticket: int
    symbol: str
    volume_initial: float
    price_open: float
    state: int
    type: int
    time_setup: int


@dataclass(slots=True)
class FakeMT5TradeResult:
    retcode: int
    comment: str
    order: int = 0
    deal: int = 0
    volume: float = 0.0
    price: float = 0.0


class FakeMT5Backend:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_H1 = 60

    ACCOUNT_MARGIN_MODE_RETAIL_NETTING = 0
    ACCOUNT_MARGIN_MODE_EXCHANGE = 1
    ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = 2
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_CONTEST = 1
    ACCOUNT_TRADE_MODE_REAL = 2
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_SLTP = 6
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_DONE_PARTIAL = 10010
    TRADE_RETCODE_REJECT = 10013

    def __init__(self) -> None:
        now = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        timestamp = int(now.timestamp())
        self.selected_symbols: list[str] = []
        self.initialized = False
        self.shutdown_called = False
        self._last_error: tuple[int, str] = (0, "OK")
        self.order_check_result = FakeMT5TradeResult(
            retcode=self.TRADE_RETCODE_DONE,
            comment="check ok",
            volume=0.0,
            price=0.0,
        )
        self.order_send_result = FakeMT5TradeResult(
            retcode=self.TRADE_RETCODE_DONE,
            comment="done",
            order=9001,
            deal=9101,
            volume=0.0,
            price=0.0,
        )
        self.order_requests: list[dict[str, object]] = []
        self.symbols = [
            FakeMT5Symbol(name="EURUSD"),
            FakeMT5Symbol(name="XAUUSD", path="Metals\\Spot"),
        ]
        self.ticks = {
            "EURUSD": FakeMT5Tick(bid=1.101, ask=1.102, last=1.1015, time=timestamp),
        }
        self.rates = {
            ("EURUSD", self.TIMEFRAME_M1): [
                {
                    "time": timestamp - 120,
                    "open": 1.1,
                    "high": 1.11,
                    "low": 1.09,
                    "close": 1.105,
                    "tick_volume": 100,
                    "spread": 12,
                    "real_volume": 50,
                },
                {
                    "time": timestamp - 60,
                    "open": 1.105,
                    "high": 1.112,
                    "low": 1.101,
                    "close": 1.109,
                    "tick_volume": 120,
                    "spread": 10,
                    "real_volume": 60,
                },
            ]
        }
        self.account = FakeMT5Account(
            login=123456,
            server="Demo-Server",
            balance=10000.0,
            equity=10025.0,
            margin_free=9500.0,
            leverage=100,
            currency="USD",
            company="Yugen Demo",
            margin_mode=self.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING,
            trade_mode=self.ACCOUNT_TRADE_MODE_DEMO,
        )
        self.positions = [
            FakeMT5Position(
                ticket=1001,
                symbol="EURUSD",
                volume=0.2,
                type=0,
                price_open=1.095,
                profit=25.0,
            )
        ]
        self.orders = [
            FakeMT5Order(
                ticket=2001,
                symbol="EURUSD",
                volume_initial=0.3,
                price_open=1.11,
                state=1,
                type=2,
            )
        ]
        self.deals = [
            FakeMT5Deal(
                ticket=3001,
                order=2001,
                symbol="EURUSD",
                volume=0.1,
                price=1.108,
                profit=8.0,
                type=0,
                entry=1,
                time=timestamp - 30,
            )
        ]
        self.history_orders = [
            FakeMT5HistoryOrder(
                ticket=4001,
                symbol="EURUSD",
                volume_initial=0.1,
                price_open=1.106,
                state=3,
                type=0,
                time_setup=timestamp - 45,
            )
        ]

    def symbols_get(self) -> list[FakeMT5Symbol]:
        return list(self.symbols)

    def initialize(self) -> bool:
        self.initialized = True
        return True

    def shutdown(self) -> None:
        self.shutdown_called = True

    def symbol_select(self, symbol: str, enable: bool) -> bool:
        if enable and any(item.name == symbol for item in self.symbols):
            self.selected_symbols.append(symbol)
            return True
        self._last_error = (404, f"symbol not found: {symbol}")
        return False

    def symbol_info_tick(self, symbol: str) -> FakeMT5Tick | None:
        return self.ticks.get(symbol)

    def copy_rates_from_pos(
        self, symbol: str, timeframe: int, start_pos: int, count: int
    ) -> list[dict[str, float | int]] | None:
        del start_pos
        rates = self.rates.get((symbol, timeframe))
        if rates is None:
            return None
        return rates[:count]

    def account_info(self) -> FakeMT5Account:
        return self.account

    def positions_get(self, *, symbol: str | None = None) -> list[FakeMT5Position]:
        if symbol is None:
            return list(self.positions)
        return [item for item in self.positions if item.symbol == symbol]

    def orders_get(self, *, symbol: str | None = None) -> list[FakeMT5Order]:
        if symbol is None:
            return list(self.orders)
        return [item for item in self.orders if item.symbol == symbol]

    def history_deals_get(
        self, date_from: datetime, date_to: datetime, *, group: str | None = None
    ) -> list[FakeMT5Deal]:
        del date_from, date_to
        if group is None:
            return list(self.deals)
        return [item for item in self.deals if item.symbol == group]

    def history_orders_get(
        self, date_from: datetime, date_to: datetime, *, group: str | None = None
    ) -> list[FakeMT5HistoryOrder]:
        del date_from, date_to
        if group is None:
            return list(self.history_orders)
        return [item for item in self.history_orders if item.symbol == group]

    def last_error(self) -> tuple[int, str]:
        return self._last_error

    def order_check(self, request: Mapping[str, object]) -> FakeMT5TradeResult:
        self.order_requests.append(dict(request))
        result = self.order_check_result
        volume = float(cast(float | int | str, request.get("volume", result.volume)))
        price = float(cast(float | int | str, request.get("price", result.price)))
        return FakeMT5TradeResult(
            retcode=result.retcode,
            comment=result.comment,
            order=result.order,
            deal=result.deal,
            volume=volume,
            price=price,
        )

    def order_send(self, request: Mapping[str, object]) -> FakeMT5TradeResult:
        self.order_requests.append(dict(request))
        action = int(cast(int | float | str, request["action"]))
        volume = float(
            cast(float | int | str, request.get("volume", self.order_send_result.volume))
        )
        price = float(
            cast(float | int | str, request.get("price", self.order_send_result.price))
        )
        result = FakeMT5TradeResult(
            retcode=self.order_send_result.retcode,
            comment=self.order_send_result.comment,
            order=self.order_send_result.order,
            deal=self.order_send_result.deal,
            volume=volume,
            price=price,
        )
        if result.retcode not in {self.TRADE_RETCODE_DONE, self.TRADE_RETCODE_DONE_PARTIAL}:
            return result

        if action == self.TRADE_ACTION_DEAL:
            self._apply_deal_request(request, volume)
        return result

    def _apply_deal_request(self, request: Mapping[str, object], volume: float) -> None:
        symbol = str(request["symbol"])
        order_type = int(cast(int | float | str, request["type"]))
        position_ticket = request.get("position")
        if position_ticket is None:
            new_ticket = max((position.ticket for position in self.positions), default=1000) + 1
            self.positions.append(
                FakeMT5Position(
                    ticket=new_ticket,
                    symbol=symbol,
                    volume=volume,
                    type=order_type,
                    price_open=float(cast(float | int | str, request.get("price", 0.0))),
                    profit=0.0,
                )
            )
            return

        target_ticket = int(cast(int | float | str, position_ticket))
        for index, position in enumerate(self.positions):
            if position.ticket != target_ticket:
                continue
            remaining = round(position.volume - volume, 10)
            if remaining <= 0:
                del self.positions[index]
            else:
                self.positions[index] = FakeMT5Position(
                    ticket=position.ticket,
                    symbol=position.symbol,
                    volume=remaining,
                    type=position.type,
                    price_open=position.price_open,
                    profit=position.profit,
                )
            return
