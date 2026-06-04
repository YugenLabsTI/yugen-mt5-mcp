"""Typed MT5 adapter with serialized backend access."""

from __future__ import annotations

import random
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from typing import Any, Protocol, TypeVar, cast

# ---------------------------------------------------------------------------
# Stale-IPC error code allowlist (REQ-2.3)
# ---------------------------------------------------------------------------
# These are the MT5 IPC-bridge failure codes.  When the terminal IPC drops,
# MetaTrader 5 returns one of these codes — all mean "the IPC bridge is broken"
# and the correct response is to trigger a lazy reconnect.
#
# EMPIRICALLY CONFIRMED against a live Deriv terminal (2026-06):
#   -10001  IPC send failed  ← CONFIRMED in live reconnect logs
#   -10004  No IPC connection ← previously the only known code
#
# Full IPC-failure family (-10001..-10005, as documented in the MT5 SDK):
#   -10001  IPC send failed
#   -10002  IPC recv failed
#   -10003  IPC init failed
#   -10004  No IPC connection
#   -10005  IPC timeout
#
# DELIBERATELY EXCLUDED:
#   -1  ("Terminal: Call failed") = legitimate operation failure (e.g. wrong
#       symbol name).  Observed live: "Boom 1000" vs "Boom 1000 Index" returns
#       -1.  That is NOT a disconnect — it must fail loud.
#   Any other non-IPC code must also fail loud (no silent swallow).
STALE_IPC_ERROR_CODES: frozenset[int] = frozenset({-10001, -10002, -10003, -10004, -10005})

# ---------------------------------------------------------------------------
# Backoff constants (REQ-2.4, REQ-2.5)
# ---------------------------------------------------------------------------
# Max reconnect attempts per _reconnect_with_backoff() call.
_RECONNECT_MAX_ATTEMPTS: int = 3
# Base sleep between attempts in seconds.  Actual delay = base * 2**attempt + jitter.
_RECONNECT_BASE_DELAY: float = 0.5
# Hard ceiling on computed delay (seconds).
_RECONNECT_MAX_DELAY: float = 4.0

TResult = TypeVar("TResult")


class MT5AdapterError(RuntimeError):
    """Raised when the MT5 backend cannot satisfy a read request."""


class AccountMode(StrEnum):
    NETTING = "netting"
    HEDGING = "hedging"


class AccountTradeMode(StrEnum):
    DEMO = "demo"
    CONTEST = "contest"
    REAL = "real"


class Timeframe(StrEnum):
    M1 = "M1"
    M5 = "M5"
    H1 = "H1"


@dataclass(slots=True, frozen=True)
class SymbolInfo:
    symbol: str
    path: str
    visible: bool


@dataclass(slots=True, frozen=True)
class Tick:
    symbol: str
    bid: float
    ask: float
    last: float
    volume: int
    observed_at: datetime


@dataclass(slots=True, frozen=True)
class Candle:
    symbol: str
    timeframe: Timeframe
    open: float
    high: float
    low: float
    close: float
    tick_volume: int
    spread: int
    real_volume: int
    observed_at: datetime


@dataclass(slots=True, frozen=True)
class AccountSnapshot:
    login: int
    server: str
    balance: float
    equity: float
    margin_free: float
    leverage: int
    currency: str
    company: str
    account_mode: AccountMode
    trade_mode: AccountTradeMode


@dataclass(slots=True, frozen=True)
class PositionSnapshot:
    ticket: int
    symbol: str
    volume: float
    order_type: int
    price_open: float
    profit: float
    account_mode: AccountMode
    sl: float = 0.0
    tp: float = 0.0
    price_current: float = 0.0
    swap: float = 0.0
    commission: float = 0.0
    time: datetime = datetime(1970, 1, 1, tzinfo=UTC)
    magic: int = 0
    comment: str = ""


@dataclass(slots=True, frozen=True)
class OrderSnapshot:
    ticket: int
    symbol: str
    volume_initial: float
    price_open: float
    state: int
    order_type: int


@dataclass(slots=True, frozen=True)
class DealSnapshot:
    ticket: int
    order: int
    symbol: str
    volume: float
    price: float
    profit: float
    deal_type: int
    entry: int
    observed_at: datetime


@dataclass(slots=True, frozen=True)
class HistoryOrderSnapshot:
    ticket: int
    symbol: str
    volume_initial: float
    price_open: float
    state: int
    order_type: int
    observed_at: datetime


@dataclass(slots=True, frozen=True)
class TradeCheckResult:
    retcode: int
    comment: str


@dataclass(slots=True, frozen=True)
class TradeResult:
    retcode: int
    comment: str
    order: int
    deal: int
    volume: float
    price: float


@dataclass(slots=True, frozen=True)
class ConnectionState:
    """Canonical, shared connection-state shape (REQ-1.3, REQ-5.2, REQ-5.3).

    Used by both ``connection_state()`` probe (observed by doctor) and the
    ``reconnect_mt5`` tool response.  A single definition prevents structural
    drift between the two consumers.
    """

    connected: bool
    last_error_code: int
    last_error_message: str
    reconnect_attempts: int
    last_reconnect_at: datetime | None


class MetaTrader5API(Protocol):
    TIMEFRAME_M1: int
    TIMEFRAME_M5: int
    TIMEFRAME_H1: int
    ACCOUNT_MARGIN_MODE_RETAIL_NETTING: int
    ACCOUNT_MARGIN_MODE_EXCHANGE: int
    ACCOUNT_MARGIN_MODE_RETAIL_HEDGING: int
    ACCOUNT_TRADE_MODE_DEMO: int
    ACCOUNT_TRADE_MODE_CONTEST: int
    ACCOUNT_TRADE_MODE_REAL: int
    TRADE_ACTION_DEAL: int
    TRADE_ACTION_SLTP: int
    TRADE_ACTION_PENDING: int
    TRADE_ACTION_REMOVE: int
    TRADE_ACTION_MODIFY: int
    ORDER_TYPE_BUY: int
    ORDER_TYPE_SELL: int
    ORDER_TYPE_BUY_LIMIT: int
    ORDER_TYPE_SELL_LIMIT: int
    ORDER_TYPE_BUY_STOP: int
    ORDER_TYPE_SELL_STOP: int

    def symbols_get(self) -> Sequence[object] | None: ...
    def symbol_select(self, symbol: str, enable: bool) -> bool: ...
    def symbol_info_tick(self, symbol: str) -> object | None: ...
    def copy_rates_from_pos(
        self, symbol: str, timeframe: int, start_pos: int, count: int
    ) -> Sequence[object] | None: ...
    def account_info(self) -> object | None: ...
    def positions_get(self, *, symbol: str | None = None) -> Sequence[object] | None: ...
    def orders_get(self, *, symbol: str | None = None) -> Sequence[object] | None: ...
    def history_deals_get(
        self, date_from: datetime, date_to: datetime, *, group: str | None = None
    ) -> Sequence[object] | None: ...
    def history_orders_get(
        self, date_from: datetime, date_to: datetime, *, group: str | None = None
    ) -> Sequence[object] | None: ...
    def order_check(self, request: Mapping[str, object]) -> object | None: ...
    def order_send(self, request: Mapping[str, object]) -> object | None: ...
    def last_error(self) -> tuple[int, str]: ...
    # REQ-1.1 / REQ-8.2: initialize and shutdown must be on the Protocol so
    # _reconnect() can call them type-safely.  Both exist on FakeMT5Backend and
    # the real MetaTrader5 module; they were previously absent from this Protocol.
    def initialize(self) -> bool: ...
    def shutdown(self) -> None: ...


def _get_attr(payload: object, key: str) -> Any:
    if isinstance(payload, Mapping):
        return payload[key]
    try:
        return payload[key]  # type: ignore[index]
    except (KeyError, TypeError, IndexError):
        pass
    return getattr(payload, key)


def _as_float(payload: object, key: str) -> float:
    value = _get_attr(payload, key)
    return float(value)


def _as_datetime(timestamp: object) -> datetime:
    return datetime.fromtimestamp(int(cast(int | float | str, timestamp)), tz=UTC)


def load_default_backend() -> MetaTrader5API:
    try:
        import MetaTrader5 as backend
    except ImportError as error:  # pragma: no cover - exercised only with real MT5 installs
        raise MT5AdapterError("MetaTrader5 package is not installed") from error
    if not backend.initialize():
        code, detail = backend.last_error()
        raise MT5AdapterError(f"MetaTrader5 initialize failed (last_error={code}: {detail})")
    return cast(MetaTrader5API, backend)


class MT5Adapter:
    def __init__(self, backend: MetaTrader5API | None = None) -> None:
        self._backend = backend or load_default_backend()
        self._lock = Lock()
        # Reconnect tracking — initialized here, mutated by _reconnect() in slice 2.
        # REQ-1.3: both fields MUST be present from construction.
        self._reconnect_attempts: int = 0
        self._last_reconnect_at: datetime | None = None

    @property
    def trade_action_deal(self) -> int:
        return self._backend.TRADE_ACTION_DEAL

    @property
    def trade_action_sltp(self) -> int:
        return self._backend.TRADE_ACTION_SLTP

    @property
    def trade_action_pending(self) -> int:
        return self._backend.TRADE_ACTION_PENDING

    @property
    def trade_action_remove(self) -> int:
        return self._backend.TRADE_ACTION_REMOVE

    @property
    def trade_action_modify(self) -> int:
        return self._backend.TRADE_ACTION_MODIFY

    @property
    def order_type_buy(self) -> int:
        return self._backend.ORDER_TYPE_BUY

    @property
    def order_type_sell(self) -> int:
        return self._backend.ORDER_TYPE_SELL

    @property
    def order_type_buy_limit(self) -> int:
        return self._backend.ORDER_TYPE_BUY_LIMIT

    @property
    def order_type_sell_limit(self) -> int:
        return self._backend.ORDER_TYPE_SELL_LIMIT

    @property
    def order_type_buy_stop(self) -> int:
        return self._backend.ORDER_TYPE_BUY_STOP

    @property
    def order_type_sell_stop(self) -> int:
        return self._backend.ORDER_TYPE_SELL_STOP

    def list_symbols(self) -> list[SymbolInfo]:
        rows = self._call("symbols_get", self._backend.symbols_get)
        return [
            SymbolInfo(
                symbol=str(_get_attr(row, "name")),
                path=str(_get_attr(row, "path")),
                visible=bool(_get_attr(row, "visible")),
            )
            for row in rows
        ]

    def get_tick(self, symbol: str) -> Tick:
        self._ensure_symbol_selected(symbol)
        row = self._call_single(
            "symbol_info_tick",
            lambda: self._backend.symbol_info_tick(symbol),
            empty_message=f"tick not available for symbol: {symbol}",
        )
        return Tick(
            symbol=symbol,
            bid=_as_float(row, "bid"),
            ask=_as_float(row, "ask"),
            last=_as_float(row, "last"),
            volume=int(_get_attr(row, "volume")),
            observed_at=_as_datetime(_get_attr(row, "time")),
        )

    def get_candles(self, symbol: str, timeframe: Timeframe, limit: int) -> list[Candle]:
        self._ensure_symbol_selected(symbol)
        timeframe_code = self._timeframe_code(timeframe)
        rows = self._call_rows(
            "copy_rates_from_pos",
            lambda: self._backend.copy_rates_from_pos(symbol, timeframe_code, 0, limit),
            empty_message=f"candles not available for symbol/timeframe: {symbol}/{timeframe.value}",
        )
        return [
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                open=_as_float(row, "open"),
                high=_as_float(row, "high"),
                low=_as_float(row, "low"),
                close=_as_float(row, "close"),
                tick_volume=int(_get_attr(row, "tick_volume")),
                spread=int(_get_attr(row, "spread")),
                real_volume=int(_get_attr(row, "real_volume")),
                observed_at=_as_datetime(_get_attr(row, "time")),
            )
            for row in rows
        ]

    def get_account(self) -> AccountSnapshot:
        row = self._call_single(
            "account_info",
            self._backend.account_info,
            empty_message="account info unavailable",
        )
        return AccountSnapshot(
            login=int(_get_attr(row, "login")),
            server=str(_get_attr(row, "server")),
            balance=_as_float(row, "balance"),
            equity=_as_float(row, "equity"),
            margin_free=_as_float(row, "margin_free"),
            leverage=int(_get_attr(row, "leverage")),
            currency=str(_get_attr(row, "currency")),
            company=str(_get_attr(row, "company")),
            account_mode=self._account_mode(int(_get_attr(row, "margin_mode"))),
            trade_mode=self._trade_mode(int(_get_attr(row, "trade_mode"))),
        )

    def list_positions(self, symbol: str | None = None) -> list[PositionSnapshot]:
        account_mode = self.get_account().account_mode
        callback = (
            self._backend.positions_get
            if symbol is None
            else lambda: self._backend.positions_get(symbol=symbol)
        )
        rows = self._call(
            "positions_get",
            callback,
        )
        return [
            PositionSnapshot(
                ticket=int(_get_attr(row, "ticket")),
                symbol=str(_get_attr(row, "symbol")),
                volume=_as_float(row, "volume"),
                order_type=int(_get_attr(row, "type")),
                price_open=_as_float(row, "price_open"),
                profit=_as_float(row, "profit"),
                account_mode=account_mode,
                sl=_as_float(row, "sl"),
                tp=_as_float(row, "tp"),
                price_current=_as_float(row, "price_current"),
                swap=_as_float(row, "swap"),
                commission=self._guarded_float(row, "commission"),
                time=_as_datetime(_get_attr(row, "time")),
                magic=int(_get_attr(row, "magic")),
                comment=str(_get_attr(row, "comment")),
            )
            for row in rows
        ]

    def list_orders(self, symbol: str | None = None) -> list[OrderSnapshot]:
        callback = (
            self._backend.orders_get
            if symbol is None
            else lambda: self._backend.orders_get(symbol=symbol)
        )
        rows = self._call("orders_get", callback)
        return [
            OrderSnapshot(
                ticket=int(_get_attr(row, "ticket")),
                symbol=str(_get_attr(row, "symbol")),
                volume_initial=_as_float(row, "volume_initial"),
                price_open=_as_float(row, "price_open"),
                state=int(_get_attr(row, "state")),
                order_type=int(_get_attr(row, "type")),
            )
            for row in rows
        ]

    def list_history_deals(
        self, start: datetime, end: datetime, symbol: str | None = None
    ) -> list[DealSnapshot]:
        if symbol is None:
            rows = self._call(
                "history_deals_get",
                lambda: self._backend.history_deals_get(start, end),
            )
        else:
            rows = self._call(
                "history_deals_get",
                lambda: self._backend.history_deals_get(start, end, group=symbol),
            )
        return [
            DealSnapshot(
                ticket=int(_get_attr(row, "ticket")),
                order=int(_get_attr(row, "order")),
                symbol=str(_get_attr(row, "symbol")),
                volume=_as_float(row, "volume"),
                price=_as_float(row, "price"),
                profit=_as_float(row, "profit"),
                deal_type=int(_get_attr(row, "type")),
                entry=int(_get_attr(row, "entry")),
                observed_at=_as_datetime(_get_attr(row, "time")),
            )
            for row in rows
        ]

    def list_history_orders(
        self, start: datetime, end: datetime, symbol: str | None = None
    ) -> list[HistoryOrderSnapshot]:
        if symbol is None:
            rows = self._call(
                "history_orders_get",
                lambda: self._backend.history_orders_get(start, end),
            )
        else:
            rows = self._call(
                "history_orders_get",
                lambda: self._backend.history_orders_get(start, end, group=symbol),
            )
        return [
            HistoryOrderSnapshot(
                ticket=int(_get_attr(row, "ticket")),
                symbol=str(_get_attr(row, "symbol")),
                volume_initial=_as_float(row, "volume_initial"),
                price_open=_as_float(row, "price_open"),
                state=int(_get_attr(row, "state")),
                order_type=int(_get_attr(row, "type")),
                observed_at=_as_datetime(_get_attr(row, "time_setup")),
            )
            for row in rows
        ]

    def check_trade(self, request: Mapping[str, object]) -> TradeCheckResult:
        row = self._call_single(
            "order_check",
            lambda: self._backend.order_check(request),
            empty_message="order check failed",
        )
        return TradeCheckResult(
            retcode=int(_get_attr(row, "retcode")),
            comment=str(_get_attr(row, "comment")),
        )

    def send_trade(self, request: Mapping[str, object]) -> TradeResult:
        # REQ-3.1 / REQ-3.4: NEVER retry on the write path.
        row = self._call_single(
            "order_send",
            lambda: self._backend.order_send(request),
            empty_message="trade send failed",
            retry_on_reconnect=False,
        )
        return TradeResult(
            retcode=int(_get_attr(row, "retcode")),
            comment=str(_get_attr(row, "comment")),
            order=int(_get_attr(row, "order")),
            deal=int(_get_attr(row, "deal")),
            volume=_as_float(row, "volume"),
            price=_as_float(row, "price"),
        )

    # ------------------------------------------------------------------
    # Connection-state probe (T-03 / REQ-1.3, REQ-5.2, REQ-5.3)
    # ------------------------------------------------------------------

    def connection_state(self) -> ConnectionState:
        """Read-only probe: report current IPC connection health.

        Calls ``backend.account_info()`` under the lock to determine liveness.
        On None, reads ``last_error()`` for the error tuple.
        NEVER calls ``_reconnect()`` — this method only observes.
        """
        with self._lock:
            result = self._backend.account_info()
            if result is None:
                code, detail = self._backend.last_error()
                connected = False
            else:
                code, detail = 0, "OK"
                connected = True
        return ConnectionState(
            connected=connected,
            last_error_code=code,
            last_error_message=detail,
            reconnect_attempts=self._reconnect_attempts,
            last_reconnect_at=self._last_reconnect_at,
        )

    # ------------------------------------------------------------------
    # Stale-IPC detection (T-06 / REQ-2.2, REQ-2.3)
    # ------------------------------------------------------------------

    def _is_stale_ipc(self) -> bool:
        """Return True iff the last backend error code is a known stale-IPC code.

        Unknown codes return False so callers can fail loud via existing
        ``_backend_error`` path — no silent swallow of unrelated errors.
        """
        code, _detail = self._backend.last_error()
        return code in STALE_IPC_ERROR_CODES

    def _timeframe_code(self, timeframe: Timeframe) -> int:
        mapping = {
            Timeframe.M1: self._backend.TIMEFRAME_M1,
            Timeframe.M5: self._backend.TIMEFRAME_M5,
            Timeframe.H1: self._backend.TIMEFRAME_H1,
        }
        return mapping[timeframe]

    def _account_mode(self, margin_mode: int) -> AccountMode:
        if margin_mode == self._backend.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING:
            return AccountMode.HEDGING
        if margin_mode in {
            self._backend.ACCOUNT_MARGIN_MODE_RETAIL_NETTING,
            self._backend.ACCOUNT_MARGIN_MODE_EXCHANGE,
        }:
            return AccountMode.NETTING
        raise MT5AdapterError(f"unsupported MT5 account margin mode: {margin_mode}")

    def _trade_mode(self, trade_mode: int) -> AccountTradeMode:
        if trade_mode == self._backend.ACCOUNT_TRADE_MODE_DEMO:
            return AccountTradeMode.DEMO
        if trade_mode == self._backend.ACCOUNT_TRADE_MODE_CONTEST:
            return AccountTradeMode.CONTEST
        if trade_mode == self._backend.ACCOUNT_TRADE_MODE_REAL:
            return AccountTradeMode.REAL
        raise MT5AdapterError(f"unsupported MT5 account trade mode: {trade_mode}")

    def _ensure_symbol_selected(self, symbol: str) -> None:
        if self._call_boolean(
            "symbol_select",
            lambda: self._backend.symbol_select(symbol, True),
        ):
            return
        raise self._backend_error(f"symbol selection failed for: {symbol}")

    # ------------------------------------------------------------------
    # Reconnect primitive (T-04 / REQ-1.1–1.5)
    # ------------------------------------------------------------------

    def _reconnect(self, *, trigger: str, call_attempt: int = 1) -> ConnectionState:
        """Shutdown then re-initialize the backend under self._lock.

        REQ-1.2: MUST be called while holding self._lock.
        REQ-1.4: logs attempt to stderr before each call.
        REQ-1.5: raises MT5AdapterError if initialize() returns falsy.

        Args:
            trigger: human-readable label for why the reconnect was requested.
            call_attempt: 1-based index of this attempt within the CURRENT
                _reconnect_with_backoff() call.  This is the per-call counter,
                NOT the cumulative lifetime counter — so separate reconnect
                calls always log attempt=1/MAX for their first retry.
        """
        code, detail = self._backend.last_error()
        print(
            f"[mt5-reconnect] trigger={trigger} attempt={call_attempt}/{_RECONNECT_MAX_ATTEMPTS}"
            f" last_error={code}:{detail}"
            f" ts={datetime.now(UTC).isoformat()}",
            file=sys.stderr,
        )
        self._backend.shutdown()
        ok = self._backend.initialize()
        if not ok:
            self._reconnect_attempts += 1
            self._last_reconnect_at = datetime.now(UTC)
            print(
                f"[mt5-reconnect] FAILED trigger={trigger} attempt={call_attempt}"
                f" last_error={code}:{detail}",
                file=sys.stderr,
            )
            raise MT5AdapterError(
                f"reconnect failed: initialize() returned falsy "
                f"(last_error={code}: {detail})"
            )
        self._reconnect_attempts += 1
        self._last_reconnect_at = datetime.now(UTC)
        print(
            f"[mt5-reconnect] reconnected trigger={trigger} attempts={self._reconnect_attempts}"
            f" ts={self._last_reconnect_at.isoformat()}",
            file=sys.stderr,
        )
        err_code, err_detail = self._backend.last_error()
        return ConnectionState(
            connected=True,
            last_error_code=err_code,
            last_error_message=err_detail,
            reconnect_attempts=self._reconnect_attempts,
            last_reconnect_at=self._last_reconnect_at,
        )

    # ------------------------------------------------------------------
    # Backoff loop (T-05 / REQ-2.4, REQ-2.5)
    # ------------------------------------------------------------------

    def _reconnect_with_backoff(self, operation: str, *, trigger: str) -> ConnectionState:
        """Bounded exponential backoff reconnect loop.

        CRITICAL: sleeps happen OUTSIDE self._lock so other tool calls are not
        blocked for the full backoff window.  Each _reconnect() call re-acquires
        the lock individually (lock is non-reentrant — must not be held here).
        """
        import time  # noqa: PLC0415  — lazy import to avoid cost on the happy path

        last_error: MT5AdapterError | None = None
        for attempt in range(_RECONNECT_MAX_ATTEMPTS):
            if attempt > 0:
                delay = min(_RECONNECT_BASE_DELAY * (2 ** attempt), _RECONNECT_MAX_DELAY)
                delay += random.uniform(0, _RECONNECT_BASE_DELAY)
                time.sleep(delay)
            try:
                with self._lock:
                    state = self._reconnect(trigger=trigger, call_attempt=attempt + 1)
                # Verify liveness after lock is released
                probe = self._backend.account_info()
                if probe is not None:
                    return state
                # initialize() returned True but backend still not responsive
                # (edge case with some MT5 builds); treat as failure and retry
                last_error = MT5AdapterError(
                    f"reconnect reported success but backend unresponsive (op={operation})"
                )
            except MT5AdapterError as exc:
                last_error = exc
                continue
        code, detail = self._backend.last_error()
        print(
            f"[mt5-reconnect] FAILED trigger={trigger} after {_RECONNECT_MAX_ATTEMPTS} attempts"
            f" last_error={code}:{detail}",
            file=sys.stderr,
        )
        raise MT5AdapterError(
            f"MT5 terminal unreachable after {_RECONNECT_MAX_ATTEMPTS} reconnect attempts"
            f" (op={operation}, last_error={code}: {detail})"
        ) from last_error

    # ------------------------------------------------------------------
    # Public force-reconnect (T-09 / REQ-4.1–4.6)
    # ------------------------------------------------------------------

    def force_reconnect(self) -> ConnectionState:
        """Explicit reconnect trigger (MCP tool path).

        Returns failure-as-data (ConnectionState with connected=False) instead
        of raising so the tool caller always gets structured feedback.
        REQ-4.5: MUST NOT propagate unhandled exceptions to MCP transport.
        """
        print(
            f"[mt5-reconnect] trigger=explicit ts={datetime.now(UTC).isoformat()}",
            file=sys.stderr,
        )
        try:
            return self._reconnect_with_backoff("force_reconnect", trigger="explicit")
        except MT5AdapterError:
            code, detail = self._backend.last_error()
            return ConnectionState(
                connected=False,
                last_error_code=code,
                last_error_message=detail,
                reconnect_attempts=self._reconnect_attempts,
                last_reconnect_at=self._last_reconnect_at,
            )

    def _call(
        self,
        operation: str,
        callback: Callable[[], Sequence[object] | None],
        *,
        retry_on_reconnect: bool = True,
    ) -> list[object]:
        with self._lock:
            result = callback()
        reconnected = False
        if result is None:
            if retry_on_reconnect and self._is_stale_ipc():
                # Lock is released — safe to call _reconnect_with_backoff (non-reentrant lock)
                self._reconnect_with_backoff(operation, trigger="lazy")
                reconnected = True
                with self._lock:
                    result = callback()
            if result is None:
                msg = f"MT5 returned no result for {operation}"
                if reconnected:
                    msg = f"after reconnect: {msg}"
                raise self._backend_error(msg)
        return list(result)

    def _call_rows(
        self,
        operation: str,
        callback: Callable[[], Sequence[object] | None],
        *,
        empty_message: str,
        retry_on_reconnect: bool = True,
    ) -> list[object]:
        rows = self._call_single(
            operation, callback, empty_message=empty_message, retry_on_reconnect=retry_on_reconnect
        )
        return list(rows)

    def _call_single(
        self,
        operation: str,
        callback: Callable[[], TResult | None],
        *,
        empty_message: str,
        retry_on_reconnect: bool = True,
    ) -> TResult:
        with self._lock:
            result = callback()
        reconnected = False
        if result is None:
            if retry_on_reconnect and self._is_stale_ipc():
                # Lock released — safe to call _reconnect_with_backoff
                self._reconnect_with_backoff(operation, trigger="lazy")
                reconnected = True
                with self._lock:
                    result = callback()
            if result is None:
                msg = f"after reconnect: {empty_message}" if reconnected else empty_message
                raise self._backend_error(msg, operation=operation)
        return result

    def _call_boolean(
        self,
        operation: str,
        callback: Callable[[], bool],
        *,
        retry_on_reconnect: bool = True,
    ) -> bool:
        with self._lock:
            result = callback()
        if result is False:
            if retry_on_reconnect and self._is_stale_ipc():
                self._reconnect_with_backoff(operation, trigger="lazy")
                with self._lock:
                    result = callback()
            if result is False:
                return False
        if result is True:
            return True
        raise self._backend_error(f"MT5 returned non-boolean result for {operation}")

    def _guarded_float(self, payload: object, key: str, fallback: float = 0.0) -> float:
        """Read a float attribute that may be absent on some MT5 builds (e.g. commission)."""
        try:
            return _as_float(payload, key)
        except (AttributeError, KeyError, TypeError):
            return fallback

    def _backend_error(self, message: str, *, operation: str | None = None) -> MT5AdapterError:
        code, detail = self._backend.last_error()
        prefix = f"{operation}: " if operation else ""
        return MT5AdapterError(f"{prefix}{message} (last_error={code}: {detail})")
