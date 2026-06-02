"""FastMCP server composition for read-only tools."""

from __future__ import annotations

from fastmcp import FastMCP

from .doctor import DoctorService
from .market_data import MarketDataService, to_payload


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


def create_server(
    market_data: MarketDataService,
    doctor_service: DoctorService | None = None,
) -> FastMCP:
    mcp = FastMCP(name="Yugen MT5 MCP")
    register_market_data_tools(mcp, market_data)
    if doctor_service is not None:
        register_doctor_tools(mcp, doctor_service)

    return mcp
