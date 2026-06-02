"""Controlled trading service with risk validation and idempotency."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from .audit import AuditEvent, AuditStore
from .mt5_adapter import (
    AccountMode,
    MT5Adapter,
    PositionSnapshot,
    TradeCheckResult,
    TradeResult,
)
from .risk import RiskApproval, RiskCheckRequest, RiskPolicy, TradeAction

_BULK_FILTER_ALL = "all"
_BULK_FILTER_PROFITABLE = "profitable"
_BULK_FILTER_LOSING = "losing"

_SUCCESS_RETCODES = {10009, 10010}


class TradeSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class TradingError(ValueError):
    """Raised when a trading request is invalid or unsafe."""


@dataclass(slots=True, frozen=True)
class ExecutedTrade:
    idempotency_key: str
    action: str
    symbol: str
    requested_volume: Decimal
    retcode: int
    order: int
    deal: int
    executed_volume: float
    executed_price: float
    comment: str
    duplicate: bool = False
    applied_sl: float | None = None
    applied_tp: float | None = None
    deviation: int | None = None
    position: int | None = None
    dry_run: bool = False


@dataclass(slots=True, frozen=True)
class BulkItemResult:
    ticket: int
    symbol: str
    status: Literal["executed", "failed", "skipped"]
    executed: ExecutedTrade | None = None
    error: str | None = None


@dataclass(slots=True, frozen=True)
class BulkTradeResult:
    action: str
    requested: int
    succeeded: int
    failed: int
    mode: Literal["best_effort", "fail_fast"]
    items: list[BulkItemResult]


class TradingService:
    def __init__(
        self,
        *,
        adapter: MT5Adapter,
        risk_policy: RiskPolicy,
        audit_store: AuditStore,
        actor: str = "mcp.trade",
    ) -> None:
        self._adapter = adapter
        self._risk_policy = risk_policy
        self._audit_store = audit_store
        self._actor = actor
        self._executed_requests: dict[str, ExecutedTrade] = {}

    def open_position(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        symbol: str,
        side: TradeSide,
        volume: Decimal,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        comment: str | None = None,
        dry_run: bool = False,
    ) -> ExecutedTrade:
        account = self._adapter.get_account()
        positions = self._adapter.list_positions(symbol)
        approval = self._risk_policy.validate(
            RiskCheckRequest(
                session_id=session_id,
                actor=self._actor,
                action=TradeAction.OPEN,
                symbol=symbol,
                volume=volume,
                account=account,
                positions=positions,
            )
        )
        tick = self._adapter.get_tick(symbol)
        order_type = self._order_type_for_side(side)
        price = tick.ask if side is TradeSide.BUY else tick.bid
        request = self._build_request(
            action=self._adapter.trade_action_deal,
            symbol=symbol,
            volume=volume,
            order_type=order_type,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            comment=comment,
        )
        return self._execute_trade(
            approval=approval,
            idempotency_key=idempotency_key,
            request=request,
            dry_run=dry_run,
        )

    def close_position(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        symbol: str,
        volume: Decimal,
        ticket: int | None = None,
        dry_run: bool = False,
    ) -> ExecutedTrade:
        account = self._adapter.get_account()
        positions = self._adapter.list_positions(symbol)
        target_position = self._resolve_close_target(
            account_mode=account.account_mode,
            symbol=symbol,
            volume=volume,
            ticket=ticket,
            positions=positions,
        )
        approval = self._risk_policy.validate(
            RiskCheckRequest(
                session_id=session_id,
                actor=self._actor,
                action=TradeAction.CLOSE,
                symbol=symbol,
                volume=volume,
                account=account,
                positions=positions,
            )
        )
        tick = self._adapter.get_tick(symbol)
        order_type = self._close_order_type(target_position)
        price = tick.bid if order_type == self._adapter.order_type_sell else tick.ask
        request = self._build_request(
            action=self._adapter.trade_action_deal,
            symbol=symbol,
            volume=volume,
            order_type=order_type,
            price=price,
            position=target_position.ticket,
        )
        return self._execute_trade(
            approval=approval,
            idempotency_key=idempotency_key,
            request=request,
            dry_run=dry_run,
        )

    def modify_position_levels(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        symbol: str,
        ticket: int,
        stop_loss: float | None,
        take_profit: float | None,
        dry_run: bool = False,
    ) -> ExecutedTrade:
        account = self._adapter.get_account()
        positions = self._adapter.list_positions(symbol)
        target_position = self._find_position(ticket=ticket, symbol=symbol, positions=positions)
        approval = self._risk_policy.validate(
            RiskCheckRequest(
                session_id=session_id,
                actor=self._actor,
                action=TradeAction.MODIFY,
                symbol=symbol,
                volume=Decimal(str(target_position.volume)),
                account=account,
                positions=positions,
            )
        )
        request = self._build_request(
            action=self._adapter.trade_action_sltp,
            symbol=symbol,
            volume=Decimal(str(target_position.volume)),
            order_type=target_position.order_type,
            position=ticket,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        return self._execute_trade(
            approval=approval,
            idempotency_key=idempotency_key,
            request=request,
            dry_run=dry_run,
        )

    def _execute_trade(
        self,
        *,
        approval: RiskApproval,
        idempotency_key: str,
        request: Mapping[str, object],
        dry_run: bool = False,
    ) -> ExecutedTrade:
        self._ensure_idempotency_key(idempotency_key)
        duplicate = self._executed_requests.get(idempotency_key)
        if duplicate is not None:
            self._audit(
                "trade.execute",
                approval.request_id,
                "duplicate",
                {"idempotency_key": idempotency_key},
            )
            return ExecutedTrade(**{**asdict(duplicate), "duplicate": True})

        check_result = self._adapter.check_trade(request)
        self._ensure_success_retcode(
            "order_check",
            check_result,
            approval=approval,
            idempotency_key=idempotency_key,
        )

        # --- dry-run branch: validate only, do NOT send or cache ---
        if dry_run:
            return ExecutedTrade(
                idempotency_key=idempotency_key,
                action=approval.action.value,
                symbol=approval.symbol,
                requested_volume=approval.volume,
                retcode=check_result.retcode,
                order=0,
                deal=0,
                executed_volume=check_result.volume,
                executed_price=check_result.price,
                comment=check_result.comment,
                dry_run=True,
            )

        trade_result = self._adapter.send_trade(request)
        self._ensure_success_retcode(
            "order_send",
            trade_result,
            approval=approval,
            idempotency_key=idempotency_key,
        )

        executed = ExecutedTrade(
            idempotency_key=idempotency_key,
            action=approval.action.value,
            symbol=approval.symbol,
            requested_volume=approval.volume,
            retcode=trade_result.retcode,
            order=trade_result.order,
            deal=trade_result.deal,
            executed_volume=trade_result.volume,
            executed_price=trade_result.price,
            comment=trade_result.comment,
        )
        self._executed_requests[idempotency_key] = executed
        self._audit(
            "trade.execute",
            approval.request_id,
            "executed",
            {
                "idempotency_key": idempotency_key,
                "action": approval.action.value,
                "symbol": approval.symbol,
                "requested_volume": str(approval.volume),
                "check_retcode": check_result.retcode,
                "trade_retcode": trade_result.retcode,
                "order": trade_result.order,
                "deal": trade_result.deal,
            },
        )
        return executed

    def _resolve_close_target(
        self,
        *,
        account_mode: AccountMode,
        symbol: str,
        volume: Decimal,
        ticket: int | None,
        positions: list[PositionSnapshot],
    ) -> PositionSnapshot:
        if account_mode is AccountMode.HEDGING:
            if ticket is None:
                raise TradingError("hedging partial/full close requires a target ticket")
            position = self._find_position(ticket=ticket, symbol=symbol, positions=positions)
        else:
            if not positions:
                raise TradingError(f"no netting position found for symbol: {symbol}")
            if len(positions) != 1:
                raise TradingError("netting close requires exactly one position for the symbol")
            position = positions[0]
            if ticket is not None and ticket != position.ticket:
                raise TradingError("ticket does not match the netting position for the symbol")

        if volume > Decimal(str(position.volume)):
            raise TradingError("close volume exceeds the current position volume")
        return position

    def _find_position(
        self,
        *,
        ticket: int,
        symbol: str,
        positions: list[PositionSnapshot],
    ) -> PositionSnapshot:
        for position in positions:
            if position.ticket == ticket and position.symbol == symbol:
                return position
        raise TradingError(f"position ticket not found for symbol: {ticket}/{symbol}")

    def _build_request(
        self,
        *,
        action: int,
        symbol: str,
        volume: Decimal,
        order_type: int,
        price: float | None = None,
        position: int | None = None,
        order: int | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        comment: str | None = None,
    ) -> dict[str, object]:
        request: dict[str, object] = {
            "action": action,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
        }
        if price is not None:
            request["price"] = price
        if position is not None:
            request["position"] = position
        if order is not None:
            request["order"] = order
        if stop_loss is not None:
            request["sl"] = stop_loss
        if take_profit is not None:
            request["tp"] = take_profit
        if comment is not None:
            request["comment"] = comment
        return request

    def place_pending_order(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        symbol: str,
        order_type: str,
        volume: Decimal,
        price: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        comment: str | None = None,
        dry_run: bool = False,
    ) -> ExecutedTrade:
        account = self._adapter.get_account()
        positions = self._adapter.list_positions(symbol)
        approval = self._risk_policy.validate(
            RiskCheckRequest(
                session_id=session_id,
                actor=self._actor,
                action=TradeAction.PLACE_PENDING,
                symbol=symbol,
                volume=volume,
                account=account,
                positions=positions,
            )
        )
        mt5_order_type = self._order_type_for_pending(order_type)
        request = self._build_request(
            action=self._adapter.trade_action_pending,
            symbol=symbol,
            volume=volume,
            order_type=mt5_order_type,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            comment=comment,
        )
        return self._execute_trade(
            approval=approval,
            idempotency_key=idempotency_key,
            request=request,
            dry_run=dry_run,
        )

    def modify_pending_order(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        ticket: int,
        symbol: str,
        price: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        dry_run: bool = False,
    ) -> ExecutedTrade:
        account = self._adapter.get_account()
        orders = self._adapter.list_orders(symbol)
        target_order = self._find_order(ticket=ticket, symbol=symbol, orders=orders)
        approval = self._risk_policy.validate(
            RiskCheckRequest(
                session_id=session_id,
                actor=self._actor,
                action=TradeAction.MODIFY,
                symbol=symbol,
                volume=Decimal(str(target_order.volume_initial)),
                account=account,
                positions=self._adapter.list_positions(symbol),
            )
        )
        request = self._build_order_request(
            action=self._adapter.trade_action_modify,
            order=ticket,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        return self._execute_trade(
            approval=approval,
            idempotency_key=idempotency_key,
            request=request,
            dry_run=dry_run,
        )

    def cancel_pending_order(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        ticket: int,
        symbol: str,
        dry_run: bool = False,
    ) -> ExecutedTrade:
        account = self._adapter.get_account()
        orders = self._adapter.list_orders(symbol)
        target_order = self._find_order(ticket=ticket, symbol=symbol, orders=orders)
        approval = self._risk_policy.validate(
            RiskCheckRequest(
                session_id=session_id,
                actor=self._actor,
                action=TradeAction.CANCEL_PENDING,
                symbol=symbol,
                volume=Decimal(str(target_order.volume_initial)),
                account=account,
                positions=self._adapter.list_positions(symbol),
            )
        )
        request = self._build_order_request(
            action=self._adapter.trade_action_remove,
            order=ticket,
        )
        return self._execute_trade(
            approval=approval,
            idempotency_key=idempotency_key,
            request=request,
            dry_run=dry_run,
        )

    def _order_type_for_side(self, side: TradeSide) -> int:
        if side is TradeSide.BUY:
            return self._adapter.order_type_buy
        return self._adapter.order_type_sell

    def _close_order_type(self, position: PositionSnapshot) -> int:
        if position.order_type == self._adapter.order_type_buy:
            return self._adapter.order_type_sell
        return self._adapter.order_type_buy

    def _find_order(
        self,
        *,
        ticket: int,
        symbol: str,
        orders: list[Any],
    ) -> Any:
        for order in orders:
            if order.ticket == ticket and order.symbol == symbol:
                return order
        raise TradingError(f"order ticket not found for symbol: {ticket}/{symbol}")

    def _build_order_request(
        self,
        *,
        action: int,
        order: int,
        price: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> dict[str, object]:
        request: dict[str, object] = {
            "action": action,
            "order": order,
        }
        if price is not None:
            request["price"] = price
        if stop_loss is not None:
            request["sl"] = stop_loss
        if take_profit is not None:
            request["tp"] = take_profit
        return request

    def _order_type_for_pending(self, order_type: str) -> int:
        mapping = {
            "buy_limit": self._adapter.order_type_buy_limit,
            "sell_limit": self._adapter.order_type_sell_limit,
            "buy_stop": self._adapter.order_type_buy_stop,
            "sell_stop": self._adapter.order_type_sell_stop,
        }
        lower = order_type.lower()
        if lower not in mapping:
            raise TradingError(
                f"unsupported order_type: {order_type!r}. "
                f"Expected one of: {list(mapping)}"
            )
        return mapping[lower]

    def _ensure_idempotency_key(self, idempotency_key: str) -> None:
        if not idempotency_key.strip():
            raise TradingError("idempotency_key is required")

    def _ensure_success_retcode(
        self,
        operation: str,
        result: TradeCheckResult | TradeResult,
        *,
        approval: RiskApproval,
        idempotency_key: str,
    ) -> None:
        if result.retcode in _SUCCESS_RETCODES:
            return
        self._audit(
            "trade.execute",
            approval.request_id,
            "rejected",
            {
                "idempotency_key": idempotency_key,
                "action": approval.action.value,
                "symbol": approval.symbol,
                "requested_volume": str(approval.volume),
                "operation": operation,
                "retcode": result.retcode,
                "comment": result.comment,
            },
        )
        raise TradingError(f"{operation} failed with retcode {result.retcode}: {result.comment}")

    def _audit(
        self,
        event_type: str,
        request_id: str,
        decision: str,
        context: dict[str, Any],
    ) -> None:
        self._audit_store.append(
            AuditEvent(
                event_type=event_type,
                actor=self._actor,
                request_id=request_id,
                decision=decision,
                context=context,
            )
        )


class BulkTradeService:
    """Composes TradingService to execute bulk operations over positions/orders.

    Best-effort mode (default): iterate all targets, collect per-item outcomes,
    never stop early — failures are data, not exceptions.

    Fail-fast mode: stop at the first failure; items processed before the
    failure retain their executed state and appear in items; remaining items
    have status="skipped".  Prior executions are NOT rolled back — caller must
    be aware of partial-state risk.
    """

    def __init__(
        self,
        *,
        trading_service: TradingService,
        adapter: MT5Adapter,
        audit_store: AuditStore,
        actor: str = "mcp.trade.bulk",
    ) -> None:
        self._trading = trading_service
        self._adapter = adapter
        self._audit_store = audit_store
        self._actor = actor

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def close_all(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        symbol: str | None = None,
        filter: Literal["all", "profitable", "losing"] = "all",  # noqa: A002
        mode: Literal["best_effort", "fail_fast"] = "best_effort",
        dry_run: bool = False,
        confirm: bool = False,
    ) -> BulkTradeResult:
        self._require_confirm(confirm)
        positions = self._adapter.list_positions(symbol)
        targets = self._apply_filter(positions, filter)
        items = self._run_close_loop(
            targets=targets,
            session_id=session_id,
            idempotency_key=idempotency_key,
            dry_run=dry_run,
            mode=mode,
        )
        result = self._build_result(action="close_all", mode=mode, items=items)
        self._audit_bulk(idempotency_key=idempotency_key, result=result)
        return result

    def cancel_all_pending(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        symbol: str | None = None,
        mode: Literal["best_effort", "fail_fast"] = "best_effort",
        dry_run: bool = False,
        confirm: bool = False,
    ) -> BulkTradeResult:
        self._require_confirm(confirm)
        orders = self._adapter.list_orders(symbol)
        items = self._run_cancel_loop(
            orders=orders,
            session_id=session_id,
            idempotency_key=idempotency_key,
            dry_run=dry_run,
            mode=mode,
        )
        result = self._build_result(action="cancel_all_pending", mode=mode, items=items)
        self._audit_bulk(idempotency_key=idempotency_key, result=result)
        return result

    # ------------------------------------------------------------------
    # Internal loop helpers
    # ------------------------------------------------------------------

    def _run_close_loop(
        self,
        *,
        targets: list[PositionSnapshot],
        session_id: str,
        idempotency_key: str,
        dry_run: bool,
        mode: Literal["best_effort", "fail_fast"],
    ) -> list[BulkItemResult]:
        items: list[BulkItemResult] = []
        failed = False
        for position in targets:
            if failed:
                items.append(
                    BulkItemResult(ticket=position.ticket, symbol=position.symbol, status="skipped")
                )
                continue
            sub_key = f"{idempotency_key}:{position.ticket}"
            try:
                executed = self._trading.close_position(
                    session_id=session_id,
                    idempotency_key=sub_key,
                    symbol=position.symbol,
                    volume=Decimal(str(position.volume)),
                    ticket=position.ticket,
                    dry_run=dry_run,
                )
                items.append(
                    BulkItemResult(
                        ticket=position.ticket,
                        symbol=position.symbol,
                        status="executed",
                        executed=executed,
                    )
                )
            except (TradingError, Exception) as exc:
                items.append(
                    BulkItemResult(
                        ticket=position.ticket,
                        symbol=position.symbol,
                        status="failed",
                        error=str(exc),
                    )
                )
                if mode == "fail_fast":
                    failed = True
        return items

    def _run_cancel_loop(
        self,
        *,
        orders: list[Any],
        session_id: str,
        idempotency_key: str,
        dry_run: bool,
        mode: Literal["best_effort", "fail_fast"],
    ) -> list[BulkItemResult]:
        items: list[BulkItemResult] = []
        failed = False
        for order in orders:
            if failed:
                items.append(
                    BulkItemResult(ticket=order.ticket, symbol=order.symbol, status="skipped")
                )
                continue
            sub_key = f"{idempotency_key}:{order.ticket}"
            try:
                executed = self._trading.cancel_pending_order(
                    session_id=session_id,
                    idempotency_key=sub_key,
                    ticket=order.ticket,
                    symbol=order.symbol,
                    dry_run=dry_run,
                )
                items.append(
                    BulkItemResult(
                        ticket=order.ticket,
                        symbol=order.symbol,
                        status="executed",
                        executed=executed,
                    )
                )
            except (TradingError, Exception) as exc:
                items.append(
                    BulkItemResult(
                        ticket=order.ticket,
                        symbol=order.symbol,
                        status="failed",
                        error=str(exc),
                    )
                )
                if mode == "fail_fast":
                    failed = True
        return items

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _require_confirm(confirm: bool) -> None:
        if not confirm:
            raise TradingError(
                "bulk operation requires confirm=True to prevent accidental mass execution"
            )

    @staticmethod
    def _apply_filter(
        positions: list[PositionSnapshot],
        filter: Literal["all", "profitable", "losing"],  # noqa: A002
    ) -> list[PositionSnapshot]:
        if filter == _BULK_FILTER_PROFITABLE:
            return [p for p in positions if p.profit > 0]
        if filter == _BULK_FILTER_LOSING:
            return [p for p in positions if p.profit < 0]
        return list(positions)

    @staticmethod
    def _build_result(
        *,
        action: str,
        mode: Literal["best_effort", "fail_fast"],
        items: list[BulkItemResult],
    ) -> BulkTradeResult:
        succeeded = sum(1 for item in items if item.status == "executed")
        failed = sum(1 for item in items if item.status == "failed")
        return BulkTradeResult(
            action=action,
            requested=len(items),
            succeeded=succeeded,
            failed=failed,
            mode=mode,
            items=items,
        )

    def _audit_bulk(self, *, idempotency_key: str, result: BulkTradeResult) -> None:
        from uuid import uuid4  # noqa: PLC0415

        self._audit_store.append(
            AuditEvent(
                event_type="trade.bulk",
                actor=self._actor,
                request_id=f"bulk-{uuid4()}",
                decision="completed",
                context={
                    "idempotency_key": idempotency_key,
                    "action": result.action,
                    "requested": result.requested,
                    "succeeded": result.succeeded,
                    "failed": result.failed,
                    "mode": result.mode,
                },
            )
        )
