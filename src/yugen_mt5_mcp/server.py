"""FastMCP server composition for read-only tools."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Annotated, cast
from uuid import uuid4

from fastmcp import FastMCP
from pydantic import BeforeValidator
from starlette.middleware import Middleware
from starlette.types import ASGIApp

from .chart_bridge import (
    ChartBridgeClient,
    ChartBridgeError,
    ChartBridgeProtocolError,
    ChartBridgeTimeoutError,
    ChartObjectPoint,
    ChartObjectSpec,
    ChartSelector,
)
from .config import AppConfig, RemoteTransportConfig
from .doctor import DoctorService
from .market_data import MarketDataService, to_payload
from .mt5_adapter import MT5Adapter
from .remote import BearerIPAuthMiddleware, trust_proxy_headers_for_bind
from .security import RemoteSecurityManager
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

CHART_TOOL_NAMES = (
    # Semantic drawing
    "draw_sl_line",
    "draw_tp_line",
    "draw_zone",
    "draw_trend_line",
    "annotate_text",
    # Generic escape-hatch
    "draw_object",
    # Management
    "list_charts",
    "delete_chart_object",
    "clear_yugen_objects",
)


_YUGEN_PREFIX = "yugen_"


def _coerce_json_arg(value: object) -> object:
    """Coerce a JSON-string tool argument into its parsed object.

    Some MCP clients (notably Claude Desktop) serialize nested object/array
    arguments as JSON strings rather than native JSON. FastMCP/Pydantic then
    rejects them against a dict/list schema before the tool body runs
    (``N validation errors ... input_type=str``). Parsing a string argument
    here restores the structured value; non-strings pass through untouched so
    native dict/list callers are unaffected. A string that is not valid JSON is
    returned as-is, letting downstream validation emit a clean error.
    """
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:  # json.JSONDecodeError is a ValueError subclass
            return value
    return value


# Tool-arg aliases that tolerate JSON-string-encoded nested values. The
# BeforeValidator runs on the RAW input before the dict/list/None union is
# validated, so a stringified object/array is parsed back into structure first.
_OptionalJsonObject = Annotated[dict[str, object] | None, BeforeValidator(_coerce_json_arg)]
_JsonObject = Annotated[dict[str, object], BeforeValidator(_coerce_json_arg)]
_JsonObjectList = Annotated[list[dict[str, object]], BeforeValidator(_coerce_json_arg)]


def _chart_error_response(error: ChartBridgeError) -> dict[str, object]:
    """Map a ChartBridgeError to a typed error dict (REQ-6).

    Matching priority:
    1. ChartBridgeTimeoutError → timeout
    2. ChartBridgeProtocolError with 'not verified' → verify_failed
    3. ChartBridgeProtocolError with 'chart_not_found' → chart_not_found
    4. ChartBridgeProtocolError with 'auth_failed' → auth_failed
    5. ChartBridgeError (base, pipe connect failure) → service_unavailable
    """
    error_message = str(error)
    if isinstance(error, ChartBridgeTimeoutError):
        code = "timeout"
    elif isinstance(error, ChartBridgeProtocolError):
        msg_lower = error_message.lower()
        if "not verified" in msg_lower:
            code = "verify_failed"
        elif "chart_not_found" in error_message:
            code = "chart_not_found"
        elif "auth_failed" in error_message:
            code = "auth_failed"
        else:
            code = "service_unavailable"
    else:
        code = "service_unavailable"
    return {"status": "error", "error_code": code, "error_message": error_message}


def _validate_iso_time(time_str: str | None) -> bool:
    """Return True when time_str is a valid ISO-8601 datetime string."""
    if not time_str:
        return False
    # Normalise the Z suffix so datetime.fromisoformat handles it on Python 3.11+
    normalised = time_str.replace("Z", "+00:00") if time_str.endswith("Z") else time_str
    try:
        datetime.fromisoformat(normalised)
        return True
    except (ValueError, TypeError):
        return False


def _invalid_params(message: str) -> dict[str, object]:
    return {"status": "error", "error_code": "invalid_params", "error_message": message}


def _disabled_response() -> dict[str, object]:
    """REQ-8.2: typed error returned by every chart tool when the bridge is disabled."""
    return {
        "status": "error",
        "error_code": "service_unavailable",
        "error_message": (
            "chart bridge is disabled: set YUGEN_MT5_CHART_SHARED_SECRET to enable"
        ),
    }


def register_chart_tools(mcp: FastMCP, chart_client: ChartBridgeClient | None) -> None:
    """Register the 9 chart drawing tools on the given FastMCP instance (REQ-1 to REQ-3).

    Tools are ALWAYS registered regardless of whether the bridge is enabled
    (REQ-8.2). When ``chart_client`` is ``None`` (bridge disabled), each tool
    returns a ``service_unavailable`` typed error without contacting the bridge.
    """

    # ------------------------------------------------------------------ #
    # Semantic tools (REQ-1)                                               #
    # ------------------------------------------------------------------ #

    @mcp.tool
    def draw_sl_line(symbol: str, price: float, label: str = "SL") -> object:
        """Draw a red stop-loss horizontal line on the chart for the given symbol."""
        if chart_client is None:
            return _disabled_response()
        name = f"{_YUGEN_PREFIX}sl_{uuid4().hex}"
        spec = ChartObjectSpec(
            name=name,
            object_type="HLINE",
            properties={"color": "red", "style": "solid", "width": 1, "description": label},
            points=(ChartObjectPoint(price=price),),
        )
        try:
            chart_client.create_object(
                chart=ChartSelector(symbol=symbol),
                object_spec=spec,
            )
        except ChartBridgeError as error:
            return _chart_error_response(error)
        return {"name": name, "status": "ok"}

    @mcp.tool
    def draw_tp_line(symbol: str, price: float, label: str = "TP") -> object:
        """Draw a green take-profit horizontal line on the chart for the given symbol."""
        if chart_client is None:
            return _disabled_response()
        name = f"{_YUGEN_PREFIX}tp_{uuid4().hex}"
        spec = ChartObjectSpec(
            name=name,
            object_type="HLINE",
            properties={"color": "green", "style": "solid", "width": 1, "description": label},
            points=(ChartObjectPoint(price=price),),
        )
        try:
            chart_client.create_object(
                chart=ChartSelector(symbol=symbol),
                object_spec=spec,
            )
        except ChartBridgeError as error:
            return _chart_error_response(error)
        return {"name": name, "status": "ok"}

    @mcp.tool
    def draw_zone(
        symbol: str,
        price_low: float,
        price_high: float,
        label: str = "",
    ) -> object:
        """Draw a supply/demand zone rectangle between price_low and price_high."""
        if chart_client is None:
            return _disabled_response()
        if price_low >= price_high:
            return _invalid_params("price_low must be less than price_high")
        name = f"{_YUGEN_PREFIX}zone_{uuid4().hex}"
        spec = ChartObjectSpec(
            name=name,
            object_type="RECTANGLE",
            properties={"description": label},
            points=(
                ChartObjectPoint(price=price_low),
                ChartObjectPoint(price=price_high),
            ),
        )
        try:
            chart_client.create_object(
                chart=ChartSelector(symbol=symbol),
                object_spec=spec,
            )
        except ChartBridgeError as error:
            return _chart_error_response(error)
        return {"name": name, "status": "ok"}

    @mcp.tool
    def draw_trend_line(
        symbol: str,
        point1: _OptionalJsonObject,
        point2: _OptionalJsonObject,
        label: str = "",
    ) -> object:
        """Draw a trend line between two anchor points (each with time and price)."""
        if chart_client is None:
            return _disabled_response()
        if not point1 or not point2:
            return _invalid_params("both point1 and point2 are required")
        t1: str | None = str(point1.get("time")) if point1.get("time") is not None else None
        t2: str | None = str(point2.get("time")) if point2.get("time") is not None else None
        if not _validate_iso_time(t1):
            return _invalid_params(
                f"point1.time must be a valid ISO-8601 UTC datetime; got {t1!r}"
            )
        if not _validate_iso_time(t2):
            return _invalid_params(
                f"point2.time must be a valid ISO-8601 UTC datetime; got {t2!r}"
            )
        # S-C2-1: reject absent or None price — explicit 0.0 is accepted, absent key is a bug.
        if "price" not in point1 or point1["price"] is None:
            return _invalid_params("point1.price is required (got absent or None)")
        if "price" not in point2 or point2["price"] is None:
            return _invalid_params("point2.price is required (got absent or None)")
        name = f"{_YUGEN_PREFIX}trend_{uuid4().hex}"
        spec = ChartObjectSpec(
            name=name,
            object_type="TREND",
            properties={"description": label},
            points=(
                ChartObjectPoint(time=t1, price=float(cast(float, point1["price"]))),
                ChartObjectPoint(time=t2, price=float(cast(float, point2["price"]))),
            ),
        )
        try:
            chart_client.create_object(
                chart=ChartSelector(symbol=symbol),
                object_spec=spec,
            )
        except ChartBridgeError as error:
            return _chart_error_response(error)
        return {"name": name, "status": "ok"}

    @mcp.tool
    def annotate_text(symbol: str, time: str, price: float, text: str) -> object:
        """Place a text annotation at the given time/price anchor on the chart."""
        if chart_client is None:
            return _disabled_response()
        if not text or not text.strip():
            return _invalid_params("text must be non-empty")
        if not _validate_iso_time(time):
            return _invalid_params(f"time must be a valid ISO-8601 UTC datetime; got {time!r}")
        name = f"{_YUGEN_PREFIX}text_{uuid4().hex}"
        spec = ChartObjectSpec(
            name=name,
            object_type="TEXT",
            properties={"text": text},
            points=(ChartObjectPoint(time=time, price=price),),
        )
        try:
            chart_client.create_object(
                chart=ChartSelector(symbol=symbol),
                object_spec=spec,
            )
        except ChartBridgeError as error:
            return _chart_error_response(error)
        return {"name": name, "status": "ok"}

    # ------------------------------------------------------------------ #
    # Generic escape-hatch (REQ-2)                                         #
    # ------------------------------------------------------------------ #

    @mcp.tool
    def draw_object(
        object_type: str,
        properties: _JsonObject,
        points: _JsonObjectList,
        symbol: str | None = None,
        chart_id: int | None = None,
    ) -> object:
        """Generic pass-through to draw any MQL5 object type. Name is always yugen_obj_* prefixed.

        ``object_type`` accepts short ("TREND", "HLINE", "TRIANGLE", ...) or the
        canonical MQL5 enum name ("OBJ_TREND", ...). ``points`` is a list of
        ``{time, price}`` (or ``{index, price}``) anchors; the count must match
        the object (e.g. TREND/RECTANGLE=2, TRIANGLE=3, HLINE/ARROW/LABEL=1).

        Recognized ``properties`` keys (all optional):
          - ``color``: name ("red"), ``"#RRGGBB"`` RGB hex ("#FF0000" = red), or
            a raw MQL5 integer (BGR order — prefer the hex form to avoid surprises)
          - ``style``: solid | dash | dot | dashdot | dashdotdot
          - ``width``: 1–5
          - ``text``: label/text content;   ``fontsize``: int;   ``description``: tooltip
          - ``fill``: bool (rectangles);   ``ray_right``: bool (trend lines)
          - ``arrowcode``: Wingdings int for OBJ_ARROW (default 241)
          - ``corner``: ENUM_BASE_CORNER 0=left-upper, 1=left-lower, 2=right-lower,
            3=right-upper; with ``xdistance``/``ydistance`` (pixels) for pixel-anchored
            objects like OBJ_LABEL

        Ownership: the generated name is always ``yugen_obj_<uuid>`` so the safety boundary
        holds even on the generic path.
        """
        if chart_client is None:
            return _disabled_response()
        if not object_type or not object_type.strip():
            return _invalid_params("object_type must be non-empty")
        if not points:
            return _invalid_params("points must contain at least one element")
        if symbol is None and chart_id is None:
            return _invalid_params("provide symbol or chart_id to identify the target chart")
        name = f"{_YUGEN_PREFIX}obj_{uuid4().hex}"
        obj_points = tuple(
            ChartObjectPoint(
                time=str(p.get("time")) if p.get("time") is not None else None,
                price=(
                    float(cast(float, p["price"]))
                    if "price" in p and p["price"] is not None
                    else None
                ),
                index=(
                    int(cast(int, p["index"]))
                    if "index" in p and p["index"] is not None
                    else None
                ),
            )
            for p in points
        )
        spec = ChartObjectSpec(
            name=name,
            object_type=object_type,
            properties=properties,
            points=obj_points,
        )
        selector = ChartSelector(symbol=symbol, chart_id=chart_id)
        try:
            chart_client.create_object(chart=selector, object_spec=spec)
        except ChartBridgeError as error:
            return _chart_error_response(error)
        return {"name": name, "status": "ok"}

    # ------------------------------------------------------------------ #
    # Management tools (REQ-3)                                             #
    # ------------------------------------------------------------------ #

    @mcp.tool
    def list_charts() -> object:
        """Return all currently open MT5 charts (platform query — no yugen filter)."""
        if chart_client is None:
            return _disabled_response()
        try:
            charts = chart_client.list_charts()
        except ChartBridgeError as error:
            return _chart_error_response(error)
        return [
            {"chart_id": c.chart_id, "symbol": c.symbol, "timeframe": c.timeframe}
            for c in charts
        ]

    @mcp.tool
    def delete_chart_object(name: str, symbol: str | None = None) -> object:
        """Delete a single chart object. Only yugen_* objects may be deleted (REQ-4.3)."""
        if chart_client is None:
            return _disabled_response()
        if not name.startswith(_YUGEN_PREFIX):
            return {
                "status": "error",
                "error_code": "ownership_violation",
                "error_message": "Only yugen_* objects may be deleted",
            }
        selector = ChartSelector(symbol=symbol) if symbol else ChartSelector(symbol="*")
        try:
            chart_client.delete_object(chart=selector, object_name=name)
        except ChartBridgeError as error:
            return _chart_error_response(error)
        return {"name": name, "status": "ok"}

    @mcp.tool
    def clear_yugen_objects(symbol: str | None = None) -> object:
        """Delete all yugen_* objects on the specified chart, or all open charts if omitted."""
        if chart_client is None:
            return _disabled_response()
        try:
            result = chart_client.clear_objects(symbol=symbol)
        except ChartBridgeError as error:
            return _chart_error_response(error)
        return result


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


def register_reconnect_tool(mcp: FastMCP, adapter: MT5Adapter) -> None:
    """Register the reconnect_mt5 MCP tool (REQ-4.1–4.6, T-09)."""

    @mcp.tool
    def reconnect_mt5() -> object:
        """Re-establish the MT5 IPC connection.

        Returns structured success/failure data — never raises to the transport.
        This is a control-plane operation only; it NEVER places orders or
        modifies positions (REQ-4.4).
        """
        state = adapter.force_reconnect()
        return to_payload(
            {
                "success": state.connected,
                "connection_state": state,
                "reconnect_attempts": state.reconnect_attempts,
                "error": None if state.connected else state.last_error_message,
            }
        )


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


def build_http_app(
    mcp: FastMCP,
    remote_config: RemoteTransportConfig,
    security_manager: RemoteSecurityManager,
) -> ASGIApp:
    """Compose the FastMCP http_app with BearerIPAuthMiddleware installed.

    The trust decision for X-Forwarded-For is derived once at composition time
    from the bind host so the per-request middleware never recalculates it.
    """
    return mcp.http_app(
        path=remote_config.path,
        middleware=[
            Middleware(
                BearerIPAuthMiddleware,
                security_manager=security_manager,
                trust_proxy_headers=trust_proxy_headers_for_bind(remote_config.host),
            )
        ],
        stateless_http=remote_config.stateless_http,
    )


def create_server(
    market_data: MarketDataService,
    doctor_service: DoctorService | None = None,
    *,
    adapter: MT5Adapter | None = None,
    trading_service: TradingService | None = None,
    bulk_service: BulkTradeService | None = None,
    session_store: SessionRiskStore | None = None,
    config: AppConfig | None = None,
    chart_client: ChartBridgeClient | None = None,
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
    # Chart tools are ALWAYS registered (REQ-8.2). When chart_client is None the
    # bridge is disabled; each tool returns a typed service_unavailable error on
    # invocation without contacting the bridge. The tool surface is always visible.
    register_chart_tools(mcp, chart_client)
    # REQ-4.1: reconnect_mt5 tool (T-09).
    if adapter is not None:
        register_reconnect_tool(mcp, adapter)
    return mcp
