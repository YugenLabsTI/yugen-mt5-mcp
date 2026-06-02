"""TDD tests — Slice C2: typed error mapping + best-effort isolation (REQ-6, REQ-7)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

from fastmcp import FastMCP

from tests.fakes.fake_transport import FakeTransport
from yugen_mt5_mcp.audit import AuditStore
from yugen_mt5_mcp.chart_bridge import (
    ChartBridgeClient,
    ChartBridgeConfig,
    ChartBridgeError,
    ChartBridgeProtocolError,
    ChartBridgeTimeoutError,
)
from yugen_mt5_mcp.server import (  # type: ignore[attr-defined]
    _chart_error_response,
    register_chart_tools,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_client(tmp_path: Path) -> ChartBridgeClient:
    _ack = {"request_id": "r", "action": "x", "status": "ok", "verified": True}
    ok_ack = (json.dumps(_ack) + "\n").encode()
    transport = FakeTransport(ok_ack)
    return ChartBridgeClient(
        config=ChartBridgeConfig(pipe_name="tp", shared_secret="s"),
        audit_store=AuditStore(tmp_path / "a.db"),
        transport=transport,
    )


def _call_tool(mcp: FastMCP, tool_name: str, args: dict) -> dict:
    async def _run() -> object:
        from fastmcp.client import Client
        async with Client(mcp) as c:
            return await c.call_tool(tool_name, args)
    result = asyncio.run(_run())
    data = result.data  # type: ignore[attr-defined]
    # When data is a dict return it; when it's a list (list_charts) wrap it
    return data if isinstance(data, dict) else {"_list": data}


# ---------------------------------------------------------------------------
# REQ-6: _chart_error_response typed mapping
# ---------------------------------------------------------------------------

class TestChartErrorResponse:
    def test_timeout_error_maps_to_timeout_code(self) -> None:
        err = ChartBridgeTimeoutError("timed out")
        result = _chart_error_response(err)
        assert result["status"] == "error"
        assert result["error_code"] == "timeout"

    def test_protocol_error_with_not_verified_maps_to_verify_failed(self) -> None:
        err = ChartBridgeProtocolError("chart bridge ACK was not verified")
        result = _chart_error_response(err)
        assert result["status"] == "error"
        assert result["error_code"] == "verify_failed"

    def test_protocol_error_with_chart_not_found_maps_correctly(self) -> None:
        err = ChartBridgeProtocolError("chart bridge action failed: chart_not_found")
        result = _chart_error_response(err)
        assert result["status"] == "error"
        assert result["error_code"] == "chart_not_found"

    def test_protocol_error_with_auth_failed_maps_correctly(self) -> None:
        err = ChartBridgeProtocolError("chart bridge action failed: auth_failed")
        result = _chart_error_response(err)
        assert result["status"] == "error"
        assert result["error_code"] == "auth_failed"

    def test_base_error_maps_to_service_unavailable(self) -> None:
        err = ChartBridgeError("pipe connect failed")
        result = _chart_error_response(err)
        assert result["status"] == "error"
        assert result["error_code"] == "service_unavailable"

    def test_error_message_is_string_of_exception(self) -> None:
        err = ChartBridgeError("something went wrong")
        result = _chart_error_response(err)
        assert result["error_message"] == "something went wrong"


# ---------------------------------------------------------------------------
# REQ-7.1: bridge errors surfaced as typed responses, never raise to MCP layer
# ---------------------------------------------------------------------------

class TestBestEffortIsolation:
    def test_draw_sl_line_returns_error_on_timeout(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        client.create_object = MagicMock(side_effect=ChartBridgeTimeoutError("timed out"))  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "draw_sl_line", {"symbol": "EURUSD", "price": 1.085})

        assert result["status"] == "error"
        assert result["error_code"] == "timeout"

    def test_draw_tp_line_returns_error_on_service_unavailable(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        client.create_object = MagicMock(side_effect=ChartBridgeError("pipe connect failed"))  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "draw_tp_line", {"symbol": "EURUSD", "price": 1.092})

        assert result["status"] == "error"
        assert result["error_code"] == "service_unavailable"

    def test_draw_zone_returns_error_on_verify_failed(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        client.create_object = MagicMock(  # type: ignore[method-assign]
            side_effect=ChartBridgeProtocolError("chart bridge ACK was not verified")
        )

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(
            mcp, "draw_zone", {"symbol": "EURUSD", "price_low": 1.08, "price_high": 1.09}
        )

        assert result["status"] == "error"
        assert result["error_code"] == "verify_failed"

    def test_list_charts_returns_error_on_bridge_error(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        client.list_charts = MagicMock(side_effect=ChartBridgeError("unavailable"))  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "list_charts", {})

        assert result["status"] == "error"
        assert result["error_code"] == "service_unavailable"

    def test_delete_chart_object_returns_error_on_chart_not_found(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        client.delete_object = MagicMock(  # type: ignore[method-assign]
            side_effect=ChartBridgeProtocolError("chart bridge action failed: chart_not_found")
        )

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "delete_chart_object", {"name": "yugen_sl_abc"})

        assert result["status"] == "error"
        assert result["error_code"] == "chart_not_found"

    def test_no_exception_propagates_to_mcp_layer(self, tmp_path: Path) -> None:
        """No chart tool ever raises — all errors return structured dicts."""
        client = _fake_client(tmp_path)
        client.create_object = MagicMock(side_effect=ChartBridgeError("boom"))  # type: ignore[method-assign]
        client.list_charts = MagicMock(side_effect=ChartBridgeError("boom"))  # type: ignore[method-assign]
        client.delete_object = MagicMock(side_effect=ChartBridgeError("boom"))  # type: ignore[method-assign]
        client.clear_objects = MagicMock(side_effect=ChartBridgeError("boom"))  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)

        # None of these should raise
        _call_tool(mcp, "draw_sl_line", {"symbol": "EURUSD", "price": 1.0})
        _call_tool(mcp, "draw_tp_line", {"symbol": "EURUSD", "price": 1.0})
        _call_tool(mcp, "draw_zone", {"symbol": "EURUSD", "price_low": 1.0, "price_high": 1.1})
        _call_tool(
            mcp,
            "annotate_text",
            {"symbol": "EURUSD", "time": "2026-06-01T00:00:00Z", "price": 1.0, "text": "x"},
        )
        _call_tool(mcp, "list_charts", {})
        _call_tool(mcp, "delete_chart_object", {"name": "yugen_sl_abc"})
        _call_tool(mcp, "clear_yugen_objects", {})


# ---------------------------------------------------------------------------
# REQ-7.2: trading module never imports chart_bridge
# ---------------------------------------------------------------------------

class TestTradingIsolation:
    def test_trading_module_does_not_import_chart_bridge(self) -> None:
        """chart_bridge must not be in trading.py's imported modules."""
        import inspect

        import yugen_mt5_mcp.trading as trading_module

        source = inspect.getsource(trading_module)
        assert "chart_bridge" not in source, (
            "trading.py must not import chart_bridge — isolation is a hard requirement"
        )
