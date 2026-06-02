"""FastMCP server composition for read-only tools."""

from __future__ import annotations

from decimal import Decimal

from fastmcp import FastMCP

from .config import AppConfig
from .doctor import DoctorService
from .market_data import MarketDataService, to_payload
from .session import SessionRiskStore
from .trading import BulkTradeService, TradingService

READ_ONLY_TOOL_NAMES = (
    "list_symbols",
    "get_tick",
    "get_candles",
    "get_account",
    "list_positions",
    "list_orders",
    "get_history",
)

TRADING_TOOL_NAMES = (
    # Atomic
    "place_market_order",
    "place_pending_order",
    "modify_position",
    "modify_pending_order",
    "close_position",
    "cancel_pending_order",
    "acknowledge_real_account",
    # Bulk
    "close_all_positions",
    "close_all_by_symbol",
    "close_all_profitable",
    "close_all_losing",
    "cancel_all_pending",
    "cancel_all_pending_by_symbol",
)


def register_market_data_tools(mcp: FastMCP, market_data: MarketDataService) -> None:
    @mcp.tool
    def list_symbols() -> object:
        return to_payload(market_data.list_symbols())

    @mcp.tool
    def get_tick(symbol: str) -> object:
        return to_payload(market_data.get_tick(symbol=symbol))

    @mcp.tool
    def get_candles(symbol: str, timeframe: str, limit: int = 100) -> object:
        return to_payload(market_data.get_candles(symbol=symbol, timeframe=timeframe, limit=limit))

    @mcp.tool
    def get_account() -> object:
        return to_payload(market_data.get_account())

    @mcp.tool
    def list_positions(symbol: str | None = None) -> object:
        return to_payload(market_data.list_positions(symbol=symbol))

    @mcp.tool
    def list_orders(symbol: str | None = None) -> object:
        return to_payload(market_data.list_orders(symbol=symbol))

    @mcp.tool
    def get_history(start: str, end: str, symbol: str | None = None) -> object:
        from datetime import datetime

        return to_payload(
            market_data.get_history(
                start=datetime.fromisoformat(start),
                end=datetime.fromisoformat(end),
                symbol=symbol,
            )
        )


def register_doctor_tools(mcp: FastMCP, doctor_service: DoctorService) -> None:
    @mcp.tool
    def doctor() -> object:
        return to_payload(doctor_service.run())


def register_trading_action_tools(
    mcp: FastMCP,
    *,
    trading_service: TradingService,
    bulk_service: BulkTradeService,
    session_store: SessionRiskStore,
    config: AppConfig,
) -> None:
    """Register all 13 trading action tools on the given FastMCP instance.

    Each tool delegates to TradingService or BulkTradeService and returns
    the transparent executed-values result via to_payload.
    """
    from .trading import TradeSide  # noqa: PLC0415

    # ------------------------------------------------------------------ #
    # Atomic tools                                                         #
    # ------------------------------------------------------------------ #

    @mcp.tool
    def place_market_order(
        session_id: str,
        idempotency_key: str,
        symbol: str,
        side: str,
        volume: str,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        comment: str | None = None,
        dry_run: bool = False,
    ) -> object:
        return to_payload(
            trading_service.open_position(
                session_id=session_id,
                idempotency_key=idempotency_key,
                symbol=symbol,
                side=TradeSide(side),
                volume=Decimal(volume),
                stop_loss=stop_loss,
                take_profit=take_profit,
                comment=comment,
                dry_run=dry_run,
            )
        )

    @mcp.tool
    def place_pending_order(
        session_id: str,
        idempotency_key: str,
        symbol: str,
        order_type: str,
        volume: str,
        price: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        comment: str | None = None,
        dry_run: bool = False,
    ) -> object:
        return to_payload(
            trading_service.place_pending_order(
                session_id=session_id,
                idempotency_key=idempotency_key,
                symbol=symbol,
                order_type=order_type,
                volume=Decimal(volume),
                price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                comment=comment,
                dry_run=dry_run,
            )
        )

    @mcp.tool
    def modify_position(
        session_id: str,
        idempotency_key: str,
        symbol: str,
        ticket: int,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        dry_run: bool = False,
    ) -> object:
        return to_payload(
            trading_service.modify_position_levels(
                session_id=session_id,
                idempotency_key=idempotency_key,
                symbol=symbol,
                ticket=ticket,
                stop_loss=stop_loss,
                take_profit=take_profit,
                dry_run=dry_run,
            )
        )

    @mcp.tool
    def modify_pending_order(
        session_id: str,
        idempotency_key: str,
        ticket: int,
        symbol: str,
        price: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        dry_run: bool = False,
    ) -> object:
        return to_payload(
            trading_service.modify_pending_order(
                session_id=session_id,
                idempotency_key=idempotency_key,
                ticket=ticket,
                symbol=symbol,
                price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                dry_run=dry_run,
            )
        )

    @mcp.tool
    def close_position(
        session_id: str,
        idempotency_key: str,
        symbol: str,
        volume: str,
        ticket: int | None = None,
        dry_run: bool = False,
    ) -> object:
        return to_payload(
            trading_service.close_position(
                session_id=session_id,
                idempotency_key=idempotency_key,
                symbol=symbol,
                volume=Decimal(volume),
                ticket=ticket,
                dry_run=dry_run,
            )
        )

    @mcp.tool
    def cancel_pending_order(
        session_id: str,
        idempotency_key: str,
        ticket: int,
        symbol: str,
        dry_run: bool = False,
    ) -> object:
        return to_payload(
            trading_service.cancel_pending_order(
                session_id=session_id,
                idempotency_key=idempotency_key,
                ticket=ticket,
                symbol=symbol,
                dry_run=dry_run,
            )
        )

    @mcp.tool
    def acknowledge_real_account(
        session_id: str,
        account_login: int,
        actor: str | None = None,
    ) -> object:
        resolved_actor = actor or config.risk.default_actor
        ack = session_store.acknowledge_real_account(
            session_id=session_id,
            actor=resolved_actor,
            account_login=account_login,
        )
        return to_payload(ack)

    # ------------------------------------------------------------------ #
    # Bulk tools                                                           #
    # ------------------------------------------------------------------ #

    @mcp.tool
    def close_all_positions(
        session_id: str,
        idempotency_key: str,
        confirm: bool = False,
        mode: str = "best_effort",
        dry_run: bool = False,
    ) -> object:
        from typing import Literal  # noqa: PLC0415

        return to_payload(
            bulk_service.close_all(
                session_id=session_id,
                idempotency_key=idempotency_key,
                confirm=confirm,
                mode=mode,  # type: ignore[arg-type]
                dry_run=dry_run,
            )
        )

    @mcp.tool
    def close_all_by_symbol(
        session_id: str,
        idempotency_key: str,
        symbol: str,
        confirm: bool = False,
        mode: str = "best_effort",
        dry_run: bool = False,
    ) -> object:
        return to_payload(
            bulk_service.close_all(
                session_id=session_id,
                idempotency_key=idempotency_key,
                symbol=symbol,
                confirm=confirm,
                mode=mode,  # type: ignore[arg-type]
                dry_run=dry_run,
            )
        )

    @mcp.tool
    def close_all_profitable(
        session_id: str,
        idempotency_key: str,
        confirm: bool = False,
        mode: str = "best_effort",
        dry_run: bool = False,
    ) -> object:
        return to_payload(
            bulk_service.close_all(
                session_id=session_id,
                idempotency_key=idempotency_key,
                filter="profitable",
                confirm=confirm,
                mode=mode,  # type: ignore[arg-type]
                dry_run=dry_run,
            )
        )

    @mcp.tool
    def close_all_losing(
        session_id: str,
        idempotency_key: str,
        confirm: bool = False,
        mode: str = "best_effort",
        dry_run: bool = False,
    ) -> object:
        return to_payload(
            bulk_service.close_all(
                session_id=session_id,
                idempotency_key=idempotency_key,
                filter="losing",
                confirm=confirm,
                mode=mode,  # type: ignore[arg-type]
                dry_run=dry_run,
            )
        )

    @mcp.tool
    def cancel_all_pending(
        session_id: str,
        idempotency_key: str,
        confirm: bool = False,
        mode: str = "best_effort",
        dry_run: bool = False,
    ) -> object:
        return to_payload(
            bulk_service.cancel_all_pending(
                session_id=session_id,
                idempotency_key=idempotency_key,
                confirm=confirm,
                mode=mode,  # type: ignore[arg-type]
                dry_run=dry_run,
            )
        )

    @mcp.tool
    def cancel_all_pending_by_symbol(
        session_id: str,
        idempotency_key: str,
        symbol: str,
        confirm: bool = False,
        mode: str = "best_effort",
        dry_run: bool = False,
    ) -> object:
        return to_payload(
            bulk_service.cancel_all_pending(
                session_id=session_id,
                idempotency_key=idempotency_key,
                symbol=symbol,
                confirm=confirm,
                mode=mode,  # type: ignore[arg-type]
                dry_run=dry_run,
            )
        )


def create_server(
    market_data: MarketDataService,
    doctor_service: DoctorService | None = None,
    *,
    trading_service: TradingService | None = None,
    bulk_service: BulkTradeService | None = None,
    session_store: SessionRiskStore | None = None,
    config: AppConfig | None = None,
) -> FastMCP:
    mcp = FastMCP(name="Yugen MT5 MCP")
    register_market_data_tools(mcp, market_data)
    if doctor_service is not None:
        register_doctor_tools(mcp, doctor_service)
    if (
        trading_service is not None
        and bulk_service is not None
        and session_store is not None
        and config is not None
    ):
        register_trading_action_tools(
            mcp,
            trading_service=trading_service,
            bulk_service=bulk_service,
            session_store=session_store,
            config=config,
        )
    return mcp
