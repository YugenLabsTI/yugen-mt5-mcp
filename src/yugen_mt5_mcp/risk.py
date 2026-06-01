"""Trade risk policy checks and real-account acknowledgement gates."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from .audit import AuditEvent, AuditStore
from .config import AppConfig
from .mt5_adapter import AccountSnapshot, AccountTradeMode, PositionSnapshot
from .session import SessionRiskStore


class TradeAction(StrEnum):
    OPEN = "open"
    CLOSE = "close"
    MODIFY = "modify"


class RiskPolicyError(ValueError):
    """Raised when a trade request violates configured policy."""


@dataclass(slots=True, frozen=True)
class RiskCheckRequest:
    session_id: str
    actor: str
    action: TradeAction
    symbol: str
    volume: Decimal
    account: AccountSnapshot
    positions: Sequence[PositionSnapshot]
    destructive: bool = True


@dataclass(slots=True, frozen=True)
class RiskApproval:
    request_id: str
    action: TradeAction
    symbol: str
    volume: Decimal
    account_login: int


class RiskPolicy:
    def __init__(
        self,
        *,
        config: AppConfig,
        session_store: SessionRiskStore,
        audit_store: AuditStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._session_store = session_store
        self._audit_store = audit_store
        self._clock = clock or (lambda: datetime.now(UTC))

    def validate(self, request: RiskCheckRequest) -> RiskApproval:
        request_id = f"risk-{uuid4()}"
        try:
            normalized_symbol = self._validate_symbol(request.symbol)
            self._validate_live_trading(request.account)
            self._validate_account_mode(request.account)
            self._validate_trading_window()
            self._validate_volume(request.volume)
            if request.action is TradeAction.OPEN:
                self._validate_exposure(request.positions, request.volume)
            if request.destructive and request.account.trade_mode is AccountTradeMode.REAL:
                self._validate_real_account_ack(request.session_id, request.account.login)
        except RiskPolicyError as error:
            self._audit(
                request_id,
                request.actor,
                request.action,
                "rejected",
                request,
                {"error": str(error)},
            )
            raise

        approval = RiskApproval(
            request_id=request_id,
            action=request.action,
            symbol=normalized_symbol,
            volume=request.volume,
            account_login=request.account.login,
        )
        self._audit(request_id, request.actor, request.action, "allowed", request, {})
        return approval

    def _validate_symbol(self, symbol: str) -> str:
        normalized = symbol.strip().upper()
        if not normalized:
            raise RiskPolicyError("symbol is required")
        allowed_symbols = self._config.risk.allowed_symbols
        if allowed_symbols and normalized not in allowed_symbols:
            raise RiskPolicyError(f"symbol is not allowed: {normalized}")
        return normalized

    def _validate_live_trading(self, account: AccountSnapshot) -> None:
        if not self._config.risk.allow_live_trading:
            raise RiskPolicyError("live trading is disabled by configuration")
        if (
            account.trade_mode is AccountTradeMode.REAL
            and not self._config.risk.allow_real_accounts
        ):
            raise RiskPolicyError("real account trading is disabled by configuration")

    def _validate_account_mode(self, account: AccountSnapshot) -> None:
        allowed_modes = self._config.risk.allowed_account_modes
        if allowed_modes and account.account_mode.value not in allowed_modes:
            raise RiskPolicyError(f"account mode is not allowed: {account.account_mode.value}")

    def _validate_trading_window(self) -> None:
        start = self._config.risk.trading_window_start
        end = self._config.risk.trading_window_end
        if start is None and end is None:
            return
        if start is None or end is None:
            raise RiskPolicyError("trading window configuration must include both start and end")

        current = self._clock().astimezone(UTC).time()
        if not self._time_in_window(current, start, end):
            raise RiskPolicyError("trading is outside the configured trading window")

    def _time_in_window(self, current: time, start: time, end: time) -> bool:
        if start <= end:
            return start <= current <= end
        return current >= start or current <= end

    def _validate_volume(self, volume: Decimal) -> None:
        if volume <= 0:
            raise RiskPolicyError("volume must be greater than zero")
        if volume > self._config.risk.max_order_volume:
            raise RiskPolicyError("volume exceeds configured max_order_volume")

    def _validate_exposure(
        self,
        positions: Sequence[PositionSnapshot],
        new_volume: Decimal,
    ) -> None:
        current = sum(Decimal(str(position.volume)) for position in positions)
        if current + new_volume > self._config.risk.max_symbol_exposure:
            raise RiskPolicyError("trade would exceed configured max_symbol_exposure")

    def _validate_real_account_ack(self, session_id: str, account_login: int) -> None:
        if not self._session_store.has_real_account_ack(
            session_id=session_id,
            account_login=account_login,
        ):
            raise RiskPolicyError("real account acknowledgement is required for this session")

    def _audit(
        self,
        request_id: str,
        actor: str,
        action: TradeAction,
        decision: str,
        request: RiskCheckRequest,
        extra_context: dict[str, object],
    ) -> None:
        self._audit_store.append(
            AuditEvent(
                event_type="risk.validate_trade",
                actor=actor,
                request_id=request_id,
                decision=decision,
                context={
                    "action": action.value,
                    "session_id": request.session_id,
                    "symbol": request.symbol,
                    "volume": str(request.volume),
                    "account_login": request.account.login,
                    "account_mode": request.account.account_mode.value,
                    "trade_mode": request.account.trade_mode.value,
                    **extra_context,
                },
            )
        )
