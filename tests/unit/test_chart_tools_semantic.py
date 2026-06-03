"""TDD tests — Slice C2: semantic chart drawing MCP tools (REQ-1, REQ-4, REQ-6, REQ-8)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

from fastmcp import FastMCP

from tests.fakes.fake_transport import FakeTransport
from yugen_mt5_mcp.audit import AuditStore
from yugen_mt5_mcp.chart_bridge import (
    ChartBridgeAck,
    ChartBridgeClient,
    ChartBridgeConfig,
    ChartBridgeError,
)
from yugen_mt5_mcp.server import CHART_TOOL_NAMES, create_server, register_chart_tools

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok_ack(request_id: str = "chart-abc", action: str = "create_object") -> bytes:
    return (
        json.dumps(
            {
                "request_id": request_id,
                "action": action,
                "status": "ok",
                "verified": True,
            }
        )
        + "\n"
    ).encode("utf-8")


def _fake_client(
    tmp_path: Path,
    response: bytes | None = None,
    raises: ChartBridgeError | None = None,
) -> ChartBridgeClient:
    transport = FakeTransport(response or _ok_ack(), raises=raises)
    return ChartBridgeClient(
        config=ChartBridgeConfig(pipe_name="test_pipe", shared_secret="s3cr3t"),
        audit_store=AuditStore(tmp_path / "audit.sqlite3"),
        transport=transport,
    )


def _call_tool(mcp: FastMCP, tool_name: str, args: dict) -> dict:
    """Call a tool via the FastMCP async client and return its data dict."""
    async def _run() -> object:
        from fastmcp.client import Client
        async with Client(mcp) as c:
            return await c.call_tool(tool_name, args)
    result = asyncio.run(_run())
    # CallToolResult.data holds the deserialized tool return value
    return result.data  # type: ignore[attr-defined]


def _tool_names_from_server(mcp: FastMCP) -> list[str]:
    async def _get() -> list[str]:
        from fastmcp.client import Client
        async with Client(mcp) as client:
            tools = await client.list_tools()
            return [t.name for t in tools]
    return asyncio.run(_get())


# ---------------------------------------------------------------------------
# REQ-8.1 + REQ-8.2: tools ALWAYS registered; disabled-state returns typed error
# ---------------------------------------------------------------------------

_DISABLED_ARGS: list[tuple[str, dict]] = [
    ("draw_sl_line", {"symbol": "EURUSD", "price": 1.085}),
    ("draw_tp_line", {"symbol": "GBPUSD", "price": 1.273}),
    (
        "draw_zone",
        {"symbol": "EURUSD", "price_low": 1.082, "price_high": 1.086},
    ),
    (
        "draw_trend_line",
        {
            "symbol": "USDJPY",
            "point1": {"time": "2026-06-01T08:00:00Z", "price": 156.5},
            "point2": {"time": "2026-06-02T12:00:00Z", "price": 157.2},
        },
    ),
    (
        "annotate_text",
        {
            "symbol": "EURUSD",
            "time": "2026-06-02T09:00:00Z",
            "price": 1.084,
            "text": "signal",
        },
    ),
    (
        "draw_object",
        {
            "object_type": "OBJ_ARROW",
            "properties": {},
            "points": [{"price": 1.0}],
            "symbol": "EURUSD",
        },
    ),
    ("list_charts", {}),
    ("delete_chart_object", {"name": "yugen_sl_abc"}),
    ("clear_yugen_objects", {}),
]


class TestChartToolsRegistration:
    def test_chart_tools_present_when_client_is_none(self, tmp_path: Path) -> None:
        """REQ-8.2: chart tools ARE registered even when bridge is disabled (client=None)."""
        from tests.fakes.fake_mt5 import FakeMT5Backend
        from yugen_mt5_mcp.app import AppConfig, AuditConfig, RiskConfig
        from yugen_mt5_mcp.market_data import MarketDataService
        from yugen_mt5_mcp.mt5_adapter import MT5Adapter

        config = AppConfig(audit=AuditConfig(database_path=tmp_path / "a.db"), risk=RiskConfig())
        adapter = MT5Adapter(backend=FakeMT5Backend())
        audit_store = AuditStore(tmp_path / "a.db")
        market_data = MarketDataService(config=config, adapter=adapter, audit_store=audit_store)
        server = create_server(market_data)  # no chart_client → disabled
        names = _tool_names_from_server(server)
        for name in CHART_TOOL_NAMES:
            assert name in names, (
                f"REQ-8.2: {name!r} must be visible in the tool surface "
                "even when bridge is disabled"
            )

    def test_chart_tools_present_when_client_is_provided(self, tmp_path: Path) -> None:
        """All chart tools registered when chart_client is supplied."""
        from tests.fakes.fake_mt5 import FakeMT5Backend
        from yugen_mt5_mcp.app import AppConfig, AuditConfig, RiskConfig
        from yugen_mt5_mcp.market_data import MarketDataService
        from yugen_mt5_mcp.mt5_adapter import MT5Adapter

        config = AppConfig(audit=AuditConfig(database_path=tmp_path / "a.db"), risk=RiskConfig())
        adapter = MT5Adapter(backend=FakeMT5Backend())
        audit_store = AuditStore(tmp_path / "a.db")
        market_data = MarketDataService(config=config, adapter=adapter, audit_store=audit_store)
        client = _fake_client(tmp_path)
        server = create_server(market_data, chart_client=client)
        names = _tool_names_from_server(server)
        for name in CHART_TOOL_NAMES:
            assert name in names, f"Expected {name!r} to be registered"

    def test_trading_tools_absent_without_trading_service(self, tmp_path: Path) -> None:
        """Trading tools never affected by chart bridge registration."""
        from tests.fakes.fake_mt5 import FakeMT5Backend
        from yugen_mt5_mcp.app import AppConfig, AuditConfig, RiskConfig
        from yugen_mt5_mcp.market_data import MarketDataService
        from yugen_mt5_mcp.mt5_adapter import MT5Adapter
        from yugen_mt5_mcp.server import TRADING_TOOL_NAMES

        config = AppConfig(audit=AuditConfig(database_path=tmp_path / "a.db"), risk=RiskConfig())
        adapter = MT5Adapter(backend=FakeMT5Backend())
        audit_store = AuditStore(tmp_path / "a.db")
        market_data = MarketDataService(config=config, adapter=adapter, audit_store=audit_store)
        client = _fake_client(tmp_path)
        server = create_server(market_data, chart_client=client)
        names = _tool_names_from_server(server)
        for name in TRADING_TOOL_NAMES:
            assert name not in names


# ---------------------------------------------------------------------------
# REQ-1.1: draw_sl_line
# ---------------------------------------------------------------------------

class TestDrawSlLine:
    def test_returns_yugen_sl_prefixed_name_on_success(self, tmp_path: Path) -> None:
        """draw_sl_line returns {name: 'yugen_sl_...', status: 'ok'}."""
        client = _fake_client(tmp_path)
        ack = ChartBridgeAck(request_id="r1", action="create_object", status="ok", verified=True)
        client.create_object = MagicMock(return_value=ack)  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "draw_sl_line", {"symbol": "EURUSD", "price": 1.085})

        assert result["status"] == "ok"
        assert result["name"].startswith("yugen_sl_")

    def test_creates_hline_with_red_color(self, tmp_path: Path) -> None:
        """draw_sl_line builds HLINE spec with color=red."""
        client = _fake_client(tmp_path)
        ack = ChartBridgeAck(request_id="r1", action="create_object", status="ok", verified=True)
        client.create_object = MagicMock(return_value=ack)  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        _call_tool(mcp, "draw_sl_line", {"symbol": "EURUSD", "price": 1.085})

        spec = client.create_object.call_args.kwargs["object_spec"]
        assert spec.object_type.upper() == "HLINE"
        assert spec.properties.get("color") == "red"
        assert len(spec.points) == 1
        assert spec.points[0].price == 1.085

    def test_default_label_is_sl(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        ack = ChartBridgeAck(request_id="r1", action="create_object", status="ok", verified=True)
        client.create_object = MagicMock(return_value=ack)  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        _call_tool(mcp, "draw_sl_line", {"symbol": "EURUSD", "price": 1.085})

        spec = client.create_object.call_args.kwargs["object_spec"]
        assert spec.properties.get("description") == "SL"

    def test_custom_label_accepted(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        ack = ChartBridgeAck(request_id="r1", action="create_object", status="ok", verified=True)
        client.create_object = MagicMock(return_value=ack)  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        _call_tool(mcp, "draw_sl_line", {"symbol": "EURUSD", "price": 1.085, "label": "My SL"})

        spec = client.create_object.call_args.kwargs["object_spec"]
        assert spec.properties.get("description") == "My SL"


# ---------------------------------------------------------------------------
# REQ-1.2: draw_tp_line
# ---------------------------------------------------------------------------

class TestDrawTpLine:
    def test_returns_yugen_tp_prefixed_name_on_success(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        ack = ChartBridgeAck(request_id="r1", action="create_object", status="ok", verified=True)
        client.create_object = MagicMock(return_value=ack)  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "draw_tp_line", {"symbol": "GBPUSD", "price": 1.273})

        assert result["status"] == "ok"
        assert result["name"].startswith("yugen_tp_")

    def test_creates_hline_with_green_color(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        ack = ChartBridgeAck(request_id="r1", action="create_object", status="ok", verified=True)
        client.create_object = MagicMock(return_value=ack)  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        _call_tool(mcp, "draw_tp_line", {"symbol": "GBPUSD", "price": 1.273})

        spec = client.create_object.call_args.kwargs["object_spec"]
        assert spec.object_type.upper() == "HLINE"
        assert spec.properties.get("color") == "green"
        assert len(spec.points) == 1

    def test_default_label_is_tp(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        ack = ChartBridgeAck(request_id="r1", action="create_object", status="ok", verified=True)
        client.create_object = MagicMock(return_value=ack)  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        _call_tool(mcp, "draw_tp_line", {"symbol": "GBPUSD", "price": 1.273})

        spec = client.create_object.call_args.kwargs["object_spec"]
        assert spec.properties.get("description") == "TP"


# ---------------------------------------------------------------------------
# REQ-1.3: draw_zone
# ---------------------------------------------------------------------------

class TestDrawZone:
    def test_returns_yugen_zone_prefixed_name_on_success(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        ack = ChartBridgeAck(request_id="r1", action="create_object", status="ok", verified=True)
        client.create_object = MagicMock(return_value=ack)  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(
            mcp, "draw_zone", {"symbol": "EURUSD", "price_low": 1.082, "price_high": 1.086}
        )

        assert result["status"] == "ok"
        assert result["name"].startswith("yugen_zone_")

    def test_creates_rectangle_with_two_points(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        ack = ChartBridgeAck(request_id="r1", action="create_object", status="ok", verified=True)
        client.create_object = MagicMock(return_value=ack)  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        _call_tool(mcp, "draw_zone", {"symbol": "EURUSD", "price_low": 1.082, "price_high": 1.086})

        spec = client.create_object.call_args.kwargs["object_spec"]
        assert spec.object_type.upper() == "RECTANGLE"
        assert len(spec.points) == 2
        prices = {p.price for p in spec.points}
        assert 1.082 in prices
        assert 1.086 in prices

    def test_rejects_price_low_ge_price_high(self, tmp_path: Path) -> None:
        """draw_zone returns invalid_params when price_low >= price_high — no client call."""
        client = _fake_client(tmp_path)
        client.create_object = MagicMock()  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)

        result_eq = _call_tool(
            mcp, "draw_zone", {"symbol": "EURUSD", "price_low": 1.09, "price_high": 1.09}
        )
        assert result_eq["status"] == "error"
        assert result_eq["error_code"] == "invalid_params"

        result_gt = _call_tool(
            mcp, "draw_zone", {"symbol": "EURUSD", "price_low": 1.09, "price_high": 1.08}
        )
        assert result_gt["status"] == "error"
        assert result_gt["error_code"] == "invalid_params"
        client.create_object.assert_not_called()


# ---------------------------------------------------------------------------
# REQ-1.4: draw_trend_line
# ---------------------------------------------------------------------------

class TestDrawTrendLine:
    def test_returns_yugen_trend_prefixed_name_on_success(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        ack = ChartBridgeAck(request_id="r1", action="create_object", status="ok", verified=True)
        client.create_object = MagicMock(return_value=ack)  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "draw_trend_line", {
            "symbol": "USDJPY",
            "point1": {"time": "2026-06-01T08:00:00Z", "price": 156.5},
            "point2": {"time": "2026-06-02T12:00:00Z", "price": 157.2},
        })

        assert result["status"] == "ok"
        assert result["name"].startswith("yugen_trend_")

    def test_creates_trend_with_two_points(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        ack = ChartBridgeAck(request_id="r1", action="create_object", status="ok", verified=True)
        client.create_object = MagicMock(return_value=ack)  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        _call_tool(mcp, "draw_trend_line", {
            "symbol": "USDJPY",
            "point1": {"time": "2026-06-01T08:00:00Z", "price": 156.5},
            "point2": {"time": "2026-06-02T12:00:00Z", "price": 157.2},
        })

        spec = client.create_object.call_args.kwargs["object_spec"]
        assert spec.object_type.upper() == "TREND"
        assert len(spec.points) == 2
        assert spec.points[0].price == 156.5
        assert spec.points[1].price == 157.2

    def test_rejects_malformed_iso_time(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        client.create_object = MagicMock()  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "draw_trend_line", {
            "symbol": "USDJPY",
            "point1": {"time": "not-a-date", "price": 156.5},
            "point2": {"time": "2026-06-02T12:00:00Z", "price": 157.2},
        })

        assert result["status"] == "error"
        assert result["error_code"] == "invalid_params"
        client.create_object.assert_not_called()

    def test_rejects_missing_point(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        client.create_object = MagicMock()  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "draw_trend_line", {
            "symbol": "USDJPY",
            "point1": None,
            "point2": {"time": "2026-06-02T12:00:00Z", "price": 157.2},
        })

        assert result["status"] == "error"
        assert result["error_code"] == "invalid_params"


# ---------------------------------------------------------------------------
# REQ-1.5: annotate_text
# ---------------------------------------------------------------------------

class TestAnnotateText:
    def test_returns_yugen_text_prefixed_name_on_success(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        ack = ChartBridgeAck(request_id="r1", action="create_object", status="ok", verified=True)
        client.create_object = MagicMock(return_value=ack)  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "annotate_text", {
            "symbol": "EURUSD",
            "time": "2026-06-02T09:00:00Z",
            "price": 1.084,
            "text": "Entry signal",
        })

        assert result["status"] == "ok"
        assert result["name"].startswith("yugen_text_")

    def test_creates_text_object_with_correct_properties(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        ack = ChartBridgeAck(request_id="r1", action="create_object", status="ok", verified=True)
        client.create_object = MagicMock(return_value=ack)  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        _call_tool(mcp, "annotate_text", {
            "symbol": "EURUSD",
            "time": "2026-06-02T09:00:00Z",
            "price": 1.084,
            "text": "Entry signal",
        })

        spec = client.create_object.call_args.kwargs["object_spec"]
        assert spec.object_type.upper() == "TEXT"
        assert spec.properties.get("text") == "Entry signal"
        assert len(spec.points) == 1
        assert spec.points[0].price == 1.084
        assert spec.points[0].time == "2026-06-02T09:00:00Z"

    def test_rejects_empty_text(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        client.create_object = MagicMock()  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "annotate_text", {
            "symbol": "EURUSD", "time": "2026-06-02T09:00:00Z", "price": 1.084, "text": ""
        })

        assert result["status"] == "error"
        assert result["error_code"] == "invalid_params"
        client.create_object.assert_not_called()

    def test_rejects_malformed_iso_time(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        client.create_object = MagicMock()  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "annotate_text", {
            "symbol": "EURUSD", "time": "not-a-date", "price": 1.084, "text": "signal"
        })

        assert result["status"] == "error"
        assert result["error_code"] == "invalid_params"
        client.create_object.assert_not_called()


# ---------------------------------------------------------------------------
# REQ-8.2: disabled-state invocation — all 9 tools return service_unavailable
# ---------------------------------------------------------------------------

import pytest  # noqa: E402


class TestChartToolsDisabledBehavior:
    """REQ-8.2: when bridge is disabled (client=None), each tool returns the typed error."""

    def _make_disabled_server(self, tmp_path: Path) -> FastMCP:
        from tests.fakes.fake_mt5 import FakeMT5Backend
        from yugen_mt5_mcp.app import AppConfig, AuditConfig, RiskConfig
        from yugen_mt5_mcp.market_data import MarketDataService
        from yugen_mt5_mcp.mt5_adapter import MT5Adapter

        config = AppConfig(audit=AuditConfig(database_path=tmp_path / "a.db"), risk=RiskConfig())
        adapter = MT5Adapter(backend=FakeMT5Backend())
        audit_store = AuditStore(tmp_path / "a.db")
        market_data = MarketDataService(config=config, adapter=adapter, audit_store=audit_store)
        return create_server(market_data)  # chart_client=None → disabled

    @pytest.mark.parametrize("tool_name,args", _DISABLED_ARGS)
    def test_disabled_tool_returns_service_unavailable(
        self, tmp_path: Path, tool_name: str, args: dict
    ) -> None:
        """Every chart tool invoked when disabled MUST return service_unavailable (REQ-8.2)."""
        mcp = self._make_disabled_server(tmp_path)
        result = _call_tool(mcp, tool_name, args)
        # list_charts returns a list on success; when disabled it returns a dict
        if isinstance(result, list):
            # Should not happen in disabled state
            raise AssertionError(
                f"{tool_name!r}: expected error dict, got list — disabled guard not active"
            )
        assert result.get("status") == "error", (
            f"{tool_name!r}: expected status='error', got {result!r}"
        )
        assert result.get("error_code") == "service_unavailable", (
            f"{tool_name!r}: expected error_code='service_unavailable', "
            f"got {result.get('error_code')!r}"
        )
        msg = result.get("error_message", "")
        assert "YUGEN_MT5_CHART_SHARED_SECRET" in str(msg), (
            f"{tool_name!r}: error_message must mention YUGEN_MT5_CHART_SHARED_SECRET; got {msg!r}"
        )


# ---------------------------------------------------------------------------
# S-C2-1: draw_trend_line — absent/None price must be rejected (not silently 0.0)
# ---------------------------------------------------------------------------

class TestDrawTrendLineAbsentPrice:
    """S-C2-1: absent or None price in a trend line point must be rejected with invalid_params."""

    def test_rejects_absent_price_in_point1(self, tmp_path: Path) -> None:
        """point1 without 'price' key → invalid_params (not silently 0.0)."""
        client = _fake_client(tmp_path)
        client.create_object = MagicMock()  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "draw_trend_line", {
            "symbol": "USDJPY",
            "point1": {"time": "2026-06-01T08:00:00Z"},  # price key absent
            "point2": {"time": "2026-06-02T12:00:00Z", "price": 157.2},
        })

        assert result["status"] == "error"
        assert result["error_code"] == "invalid_params"
        client.create_object.assert_not_called()

    def test_rejects_none_price_in_point2(self, tmp_path: Path) -> None:
        """point2 with price=None → invalid_params (caller must supply an explicit float)."""
        client = _fake_client(tmp_path)
        client.create_object = MagicMock()  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "draw_trend_line", {
            "symbol": "USDJPY",
            "point1": {"time": "2026-06-01T08:00:00Z", "price": 156.5},
            "point2": {"time": "2026-06-02T12:00:00Z", "price": None},
        })

        assert result["status"] == "error"
        assert result["error_code"] == "invalid_params"
        client.create_object.assert_not_called()

    def test_accepts_explicit_zero_price(self, tmp_path: Path) -> None:
        """An explicit price=0.0 from the caller is allowed — it's a deliberate choice."""
        client = _fake_client(tmp_path)
        ack = ChartBridgeAck(request_id="r1", action="create_object", status="ok", verified=True)
        client.create_object = MagicMock(return_value=ack)  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "draw_trend_line", {
            "symbol": "USDJPY",
            "point1": {"time": "2026-06-01T08:00:00Z", "price": 0.0},
            "point2": {"time": "2026-06-02T12:00:00Z", "price": 157.2},
        })

        # explicit 0.0 is a valid caller choice; must succeed
        assert result["status"] == "ok"
        assert result["name"].startswith("yugen_trend_")
        spec = client.create_object.call_args.kwargs["object_spec"]
        assert spec.points[0].price == 0.0
