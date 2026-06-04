from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast

_FAKE_TS = int(datetime(2024, 1, 1, 12, 0, tzinfo=UTC).timestamp())


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
    sl: float = 0.0
    tp: float = 0.0
    price_current: float = 0.0
    swap: float = 0.0
    commission: float = 0.0
    time: int = field(default_factory=lambda: _FAKE_TS)
    magic: int = 0
    comment: str = ""


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
    TRADE_ACTION_PENDING = 5
    TRADE_ACTION_REMOVE = 2
    TRADE_ACTION_MODIFY = 8
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    ORDER_TYPE_BUY_STOP = 4
    ORDER_TYPE_SELL_STOP = 5
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
        # REQ-8.1: disconnected simulation support (T-11)
        # When True, read methods return None and last_error returns -10004.
        self.disconnected: bool = False
        # REQ-8.2: counts reconnect-driven initialize() calls only (not cold starts).
        self.reconnect_count: int = 0
        # REQ-8.3: when True, initialize() returns False (terminal still down).
        self.fail_on_reconnect: bool = False
        # Track whether disconnected was True at the start of the last initialize()
        # call so reconnect_count only increments on actual reconnect attempts.
        self._was_disconnected_on_init: bool = False
        # Real MT5 order_check() returns retcode 0 / comment "Done" on success.
        self.order_check_result = FakeMT5TradeResult(
            retcode=0,
            comment="Done",
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
                price_current=1.095,
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

    def symbols_get(self) -> list[FakeMT5Symbol] | None:
        if self.disconnected:
            self._last_error = (-10004, "No IPC connection")
            return None
        return list(self.symbols)

    def initialize(self) -> bool:
        # REQ-8.2 / REQ-8.3: only count and clear disconnected on a reconnect attempt.
        was_disconnected = self.disconnected
        if was_disconnected:
            if self.fail_on_reconnect:
                # Terminal still down — do not clear disconnected, do not count.
                return False
            self.disconnected = False
            self.reconnect_count += 1
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
        if self.disconnected:
            self._last_error = (-10004, "No IPC connection")
            return None
        return self.ticks.get(symbol)

    def copy_rates_from_pos(
        self, symbol: str, timeframe: int, start_pos: int, count: int
    ) -> list[dict[str, float | int]] | None:
        if self.disconnected:
            self._last_error = (-10004, "No IPC connection")
            return None
        del start_pos
        rates = self.rates.get((symbol, timeframe))
        if rates is None:
            return None
        return rates[:count]

    def account_info(self) -> FakeMT5Account | None:
        if self.disconnected:
            self._last_error = (-10004, "No IPC connection")
            return None
        return self.account

    def positions_get(self, *, symbol: str | None = None) -> list[FakeMT5Position] | None:
        if self.disconnected:
            self._last_error = (-10004, "No IPC connection")
            return None
        if symbol is None:
            return list(self.positions)
        return [item for item in self.positions if item.symbol == symbol]

    def orders_get(self, *, symbol: str | None = None) -> list[FakeMT5Order] | None:
        if self.disconnected:
            self._last_error = (-10004, "No IPC connection")
            return None
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

    def order_send(self, request: Mapping[str, object]) -> FakeMT5TradeResult | None:
        if self.disconnected:
            self._last_error = (-10004, "No IPC connection")
            return None
        self.order_requests.append(dict(request))
        action = int(cast(int | float | str, request["action"]))
        volume = float(
            cast(float | int | str, request.get("volume", self.order_send_result.volume))
        )
        price = float(
            cast(float | int | str, request.get("price", self.order_send_result.price))
        )

        if self.order_send_result.retcode not in {
            self.TRADE_RETCODE_DONE,
            self.TRADE_RETCODE_DONE_PARTIAL,
        }:
            return FakeMT5TradeResult(
                retcode=self.order_send_result.retcode,
                comment=self.order_send_result.comment,
                order=self.order_send_result.order,
                deal=self.order_send_result.deal,
                volume=volume,
                price=price,
            )

        if action == self.TRADE_ACTION_DEAL:
            self._apply_deal_request(request, volume)
            return FakeMT5TradeResult(
                retcode=self.order_send_result.retcode,
                comment=self.order_send_result.comment,
                order=self.order_send_result.order,
                deal=self.order_send_result.deal,
                volume=volume,
                price=price,
            )
        if action == self.TRADE_ACTION_PENDING:
            self._apply_pending_request(request, volume)
            # order_send_result.order was set to the new ticket inside _apply_pending_request
            return FakeMT5TradeResult(
                retcode=self.order_send_result.retcode,
                comment=self.order_send_result.comment,
                order=self.order_send_result.order,
                deal=0,
                volume=volume,
                price=price,
            )
        if action == self.TRADE_ACTION_REMOVE:
            order_ticket = int(cast(int | float | str, request["order"]))
            self._apply_remove_request(request)
            return FakeMT5TradeResult(
                retcode=self.TRADE_RETCODE_DONE,
                comment="done",
                order=order_ticket,
                deal=0,
                volume=0.0,
                price=0.0,
            )
        if action == self.TRADE_ACTION_MODIFY:
            order_ticket = int(cast(int | float | str, request["order"]))
            self._apply_modify_request(request)
            return FakeMT5TradeResult(
                retcode=self.TRADE_RETCODE_DONE,
                comment="done",
                order=order_ticket,
                deal=0,
                volume=volume,
                price=price,
            )
        # fallback for unknown actions
        return FakeMT5TradeResult(
            retcode=self.order_send_result.retcode,
            comment=self.order_send_result.comment,
            order=self.order_send_result.order,
            deal=self.order_send_result.deal,
            volume=volume,
            price=price,
        )

    def _apply_deal_request(self, request: Mapping[str, object], volume: float) -> None:
        symbol = str(request["symbol"])
        order_type = int(cast(int | float | str, request["type"]))
        position_ticket = request.get("position")
        if position_ticket is None:
            new_ticket = max((position.ticket for position in self.positions), default=1000) + 1
            price = float(cast(float | int | str, request.get("price", 0.0)))
            sl = float(cast(float | int | str, request.get("sl", 0.0)))
            tp = float(cast(float | int | str, request.get("tp", 0.0)))
            self.positions.append(
                FakeMT5Position(
                    ticket=new_ticket,
                    symbol=symbol,
                    volume=volume,
                    type=order_type,
                    price_open=price,
                    profit=0.0,
                    sl=sl,
                    tp=tp,
                    price_current=price,
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
                    sl=position.sl,
                    tp=position.tp,
                    price_current=position.price_current,
                    swap=position.swap,
                    commission=position.commission,
                    time=position.time,
                    magic=position.magic,
                    comment=position.comment,
                )
            return

    def _apply_pending_request(self, request: Mapping[str, object], volume: float) -> None:
        new_ticket = max((o.ticket for o in self.orders), default=2000) + 1
        symbol = str(request["symbol"])
        order_type = int(cast(int | float | str, request["type"]))
        price = float(cast(float | int | str, request.get("price", 0.0)))
        self.orders.append(
            FakeMT5Order(
                ticket=new_ticket,
                symbol=symbol,
                volume_initial=volume,
                price_open=price,
                state=1,
                type=order_type,
            )
        )
        # Return ticket in the result via order_send_result override so callers get it
        self.order_send_result = FakeMT5TradeResult(
            retcode=self.TRADE_RETCODE_DONE,
            comment="done",
            order=new_ticket,
            deal=0,
            volume=volume,
            price=price,
        )

    def _apply_remove_request(self, request: Mapping[str, object]) -> None:
        order_ticket = int(cast(int | float | str, request["order"]))
        self.orders = [o for o in self.orders if o.ticket != order_ticket]

    def _apply_modify_request(self, request: Mapping[str, object]) -> None:
        order_ticket = int(cast(int | float | str, request["order"]))
        new_price = float(cast(float | int | str, request.get("price", 0.0)))
        for index, order in enumerate(self.orders):
            if order.ticket != order_ticket:
                continue
            self.orders[index] = FakeMT5Order(
                ticket=order.ticket,
                symbol=order.symbol,
                volume_initial=order.volume_initial,
                price_open=new_price if new_price else order.price_open,
                state=order.state,
                type=order.type,
            )
            # Surface the ticket as the order field in the result
            self.order_send_result = FakeMT5TradeResult(
                retcode=self.TRADE_RETCODE_DONE,
                comment="done",
                order=order_ticket,
                deal=0,
                volume=order.volume_initial,
                price=new_price if new_price else order.price_open,
            )
            return
