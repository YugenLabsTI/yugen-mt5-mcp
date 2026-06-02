"""Validated read-only market data service with audit hooks."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, TypeVar, cast
from uuid import uuid4

from .audit import AuditEvent, AuditStore
from .config import AppConfig
from .mt5_adapter import (
    AccountSnapshot,
    Candle,
    DealSnapshot,
    HistoryOrderSnapshot,
    MT5Adapter,
    MT5AdapterError,
    OrderSnapshot,
    PositionSnapshot,
    SymbolInfo,
    Tick,
    Timeframe,
)


class MarketDataError(ValueError):
    """Raised when read-only input validation fails."""


@dataclass(slots=True, frozen=True)
class HistoryWindow:
    start: datetime
    end: datetime


@dataclass(slots=True, frozen=True)
class HistorySnapshot:
    window: HistoryWindow
    deals: list[DealSnapshot]
    orders: list[HistoryOrderSnapshot]


TAuditResult = TypeVar("TAuditResult")


class MarketDataService:
    def __init__(
        self,
        *,
        config: AppConfig,
        adapter: MT5Adapter,
        audit_store: AuditStore,
        actor: str = "mcp.read",
    ) -> None:
        self._config = config
        self._adapter = adapter
        self._audit_store = audit_store
        self._actor = actor

    def list_symbols(self) -> list[SymbolInfo]:
        return self._run_audited("list_symbols", {}, self._adapter.list_symbols)

    def get_tick(self, *, symbol: str) -> Tick:
        request_id = f"read-{uuid4()}"
        try:
            normalized_symbol = self._validate_symbol(symbol)
            result = self._adapter.get_tick(normalized_symbol)
        except (MarketDataError, MT5AdapterError) as error:
            self._audit("get_tick", request_id, "rejected", {"symbol": symbol, "error": str(error)})
            raise
        self._audit("get_tick", request_id, "allowed", {"symbol": normalized_symbol})
        return result

    def get_candles(self, *, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        request_id = f"read-{uuid4()}"
        try:
            normalized_symbol = self._validate_symbol(symbol)
            normalized_timeframe = self._validate_timeframe(timeframe)
            normalized_limit = self._validate_limit(limit)
            result = self._adapter.get_candles(
                normalized_symbol,
                normalized_timeframe,
                normalized_limit,
            )
        except (MarketDataError, MT5AdapterError) as error:
            self._audit(
                "get_candles",
                request_id,
                "rejected",
                {"symbol": symbol, "timeframe": timeframe, "limit": limit, "error": str(error)},
            )
            raise
        self._audit(
            "get_candles",
            request_id,
            "allowed",
            {
                "symbol": normalized_symbol,
                "timeframe": normalized_timeframe.value,
                "limit": normalized_limit,
            },
        )
        return result

    def get_account(self) -> AccountSnapshot:
        return self._run_audited("get_account", {}, self._adapter.get_account)

    def list_positions(self, *, symbol: str | None = None) -> list[PositionSnapshot]:
        request_id = f"read-{uuid4()}"
        try:
            normalized_symbol = self._validate_optional_symbol(symbol)
            result = self._adapter.list_positions(normalized_symbol)
        except (MarketDataError, MT5AdapterError) as error:
            self._audit(
                "list_positions",
                request_id,
                "rejected",
                {"symbol": symbol, "error": str(error)},
            )
            raise
        self._audit("list_positions", request_id, "allowed", {"symbol": normalized_symbol})
        return result

    def list_orders(self, *, symbol: str | None = None) -> list[OrderSnapshot]:
        request_id = f"read-{uuid4()}"
        try:
            normalized_symbol = self._validate_optional_symbol(symbol)
            result = self._adapter.list_orders(normalized_symbol)
        except (MarketDataError, MT5AdapterError) as error:
            self._audit(
                "list_orders",
                request_id,
                "rejected",
                {"symbol": symbol, "error": str(error)},
            )
            raise
        self._audit("list_orders", request_id, "allowed", {"symbol": normalized_symbol})
        return result

    def get_history(
        self,
        *,
        start: datetime,
        end: datetime,
        symbol: str | None = None,
    ) -> HistorySnapshot:
        request_id = f"read-{uuid4()}"
        try:
            window = self._validate_window(start, end)
            normalized_symbol = self._validate_optional_symbol(symbol)
            result = HistorySnapshot(
                window=window,
                deals=self._adapter.list_history_deals(
                    window.start,
                    window.end,
                    normalized_symbol,
                ),
                orders=self._adapter.list_history_orders(
                    window.start,
                    window.end,
                    normalized_symbol,
                ),
            )
        except (MarketDataError, MT5AdapterError) as error:
            self._audit(
                "get_history",
                request_id,
                "rejected",
                {
                    "symbol": symbol,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "error": str(error),
                },
            )
            raise
        self._audit(
            "get_history",
            request_id,
            "allowed",
            {
                "symbol": normalized_symbol,
                "start": window.start.isoformat(),
                "end": window.end.isoformat(),
            },
        )
        return result

    def _validate_symbol(self, symbol: str) -> str:
        requested = symbol.strip()
        allowed = self._config.risk.allowed_symbols
        if not requested:
            raise MarketDataError("symbol is required")
        if allowed == ("*",):
            return self._resolve_broker_symbol(requested)
        if allowed:
            for allowed_symbol in allowed:
                if requested.casefold() == allowed_symbol.casefold():
                    return allowed_symbol
            raise MarketDataError(f"symbol is not allowed: {requested}")
        return requested.upper()

    def _validate_optional_symbol(self, symbol: str | None) -> str | None:
        if symbol is None:
            return None
        return self._validate_symbol(symbol)

    def _resolve_broker_symbol(self, requested: str) -> str:
        for symbol in self._adapter.list_symbols():
            if requested.casefold() == symbol.symbol.casefold():
                return symbol.symbol
        return requested

    def _validate_timeframe(self, timeframe: str) -> Timeframe:
        try:
            return Timeframe(timeframe.upper())
        except ValueError as error:
            raise MarketDataError(f"unsupported timeframe: {timeframe}") from error

    def _validate_limit(self, limit: int) -> int:
        if not 1 <= limit <= 1000:
            raise MarketDataError("limit must be between 1 and 1000")
        return limit

    def _validate_window(self, start: datetime, end: datetime) -> HistoryWindow:
        normalized_start = self._coerce_datetime(start)
        normalized_end = self._coerce_datetime(end)
        if normalized_start >= normalized_end:
            raise MarketDataError("history start must be before end")
        return HistoryWindow(start=normalized_start, end=normalized_end)

    def _coerce_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _run_audited(
        self,
        name: str,
        context: Mapping[str, Any],
        action: Callable[[], TAuditResult],
    ) -> TAuditResult:
        request_id = f"read-{uuid4()}"
        try:
            result = action()
        except (MarketDataError, MT5AdapterError) as error:
            self._audit(name, request_id, "rejected", {**context, "error": str(error)})
            raise
        self._audit(name, request_id, "allowed", context)
        return result

    def _audit(self, name: str, request_id: str, decision: str, context: Mapping[str, Any]) -> None:
        self._audit_store.append(
            AuditEvent(
                event_type=f"market_data.{name}",
                actor=self._actor,
                request_id=request_id,
                decision=decision,
                context=dict(context),
            )
        )


def to_payload(value: Any) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: to_payload(item)
            for key, item in asdict(value).items()
        }
    if isinstance(value, dict):
        return {str(key): to_payload(item) for key, item in value.items()}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [to_payload(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    return cast(object, value)
