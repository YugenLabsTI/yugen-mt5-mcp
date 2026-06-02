"""TDD tests — Slice C2: management + generic chart tools (REQ-2, REQ-3, REQ-4, REQ-6)."""

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
)
from yugen_mt5_mcp.server import register_chart_tools

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


def _call_tool(mcp: FastMCP, tool_name: str, args: dict) -> object:
    async def _run() -> object:
        from fastmcp.client import Client
        async with Client(mcp) as c:
            return await c.call_tool(tool_name, args)
    result = asyncio.run(_run())
    return result.data  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# REQ-2.1: draw_object
# ---------------------------------------------------------------------------

class TestDrawObject:
    def test_returns_yugen_obj_prefixed_name(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        ack = ChartBridgeAck(request_id="r1", action="create_object", status="ok", verified=True)
        client.create_object = MagicMock(return_value=ack)  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "draw_object", {
            "object_type": "OBJ_ARROW",
            "properties": {"arrowcode": 233, "color": 255},
            "points": [{"price": 1920.0}],
            "symbol": "XAUUSD",
        })

        assert isinstance(result, dict)
        assert result["status"] == "ok"
        assert result["name"].startswith("yugen_obj_")

    def test_always_forces_yugen_prefix_on_name(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        ack = ChartBridgeAck(request_id="r1", action="create_object", status="ok", verified=True)
        client.create_object = MagicMock(return_value=ack)  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        _call_tool(mcp, "draw_object", {
            "object_type": "OBJ_HLINE",
            "properties": {},
            "points": [{"price": 1.0}],
            "symbol": "EURUSD",
        })

        spec = client.create_object.call_args.kwargs["object_spec"]
        assert spec.name.startswith("yugen_obj_")

    def test_rejects_empty_object_type(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        client.create_object = MagicMock()  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "draw_object", {
            "object_type": "", "properties": {}, "points": [{"price": 1.0}], "symbol": "EURUSD"
        })

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "invalid_params"
        client.create_object.assert_not_called()

    def test_rejects_empty_points_list(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        client.create_object = MagicMock()  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "draw_object", {
            "object_type": "OBJ_HLINE", "properties": {}, "points": [], "symbol": "EURUSD"
        })

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "invalid_params"
        client.create_object.assert_not_called()

    def test_rejects_missing_chart_selector(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        client.create_object = MagicMock()  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "draw_object", {
            "object_type": "OBJ_HLINE", "properties": {}, "points": [{"price": 1.0}]
        })

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "invalid_params"
        client.create_object.assert_not_called()

    def test_passes_properties_raw_to_spec(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        ack = ChartBridgeAck(request_id="r1", action="create_object", status="ok", verified=True)
        client.create_object = MagicMock(return_value=ack)  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        _call_tool(mcp, "draw_object", {
            "object_type": "OBJ_ARROW",
            "properties": {"arrowcode": 233, "color": 255},
            "points": [{"price": 1920.0}],
            "symbol": "XAUUSD",
        })

        spec = client.create_object.call_args.kwargs["object_spec"]
        assert spec.properties["arrowcode"] == 233
        assert spec.properties["color"] == 255


# ---------------------------------------------------------------------------
# REQ-3.1: list_charts
# ---------------------------------------------------------------------------

class TestListCharts:
    def test_returns_all_charts_without_yugen_filter(self, tmp_path: Path) -> None:
        from yugen_mt5_mcp.chart_bridge import ChartDescriptor
        client = _fake_client(tmp_path)
        charts = [
            ChartDescriptor(chart_id=1, symbol="EURUSD", timeframe="M15"),
            ChartDescriptor(chart_id=2, symbol="GBPUSD", timeframe="H1"),
        ]
        client.list_charts = MagicMock(return_value=charts)  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "list_charts", {})

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["chart_id"] == 1
        assert result[0]["symbol"] == "EURUSD"
        assert result[0]["timeframe"] == "M15"

    def test_returns_empty_list_when_no_charts(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        client.list_charts = MagicMock(return_value=[])  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "list_charts", {})

        assert result == []


# ---------------------------------------------------------------------------
# REQ-3.2 + REQ-4.3: delete_chart_object — ownership guard (HARD)
# ---------------------------------------------------------------------------

class TestDeleteChartObject:
    def test_rejects_non_yugen_name_without_contacting_client(self, tmp_path: Path) -> None:
        """Ownership violation — bridge never contacted (REQ-4.3 HARD)."""
        client = _fake_client(tmp_path)
        client.delete_object = MagicMock()  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "delete_chart_object", {"name": "broker_sl_123"})

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "ownership_violation"
        assert "yugen_" in result["error_message"].lower()
        client.delete_object.assert_not_called()

    def test_rejects_ea_stopline_without_contacting_client(self, tmp_path: Path) -> None:
        """REQ-4 non-negotiable scenario: ea_stopline must be rejected at tool layer."""
        client = _fake_client(tmp_path)
        client.delete_object = MagicMock()  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "delete_chart_object", {"name": "ea_stopline"})

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "ownership_violation"
        client.delete_object.assert_not_called()

    def test_accepts_yugen_prefixed_name(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        ack = ChartBridgeAck(request_id="r1", action="delete_object", status="ok", verified=True)
        client.delete_object = MagicMock(return_value=ack)  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(
            mcp, "delete_chart_object", {"name": "yugen_sl_abc", "symbol": "EURUSD"}
        )

        assert isinstance(result, dict)
        assert result["status"] == "ok"
        assert result["name"] == "yugen_sl_abc"
        client.delete_object.assert_called_once()

    def test_passes_correct_name_to_client(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        ack = ChartBridgeAck(request_id="r1", action="delete_object", status="ok", verified=True)
        client.delete_object = MagicMock(return_value=ack)  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        _call_tool(mcp, "delete_chart_object", {"name": "yugen_tp_xyz", "symbol": "GBPUSD"})

        call_kwargs = client.delete_object.call_args.kwargs
        assert call_kwargs["object_name"] == "yugen_tp_xyz"


# ---------------------------------------------------------------------------
# REQ-3.3: clear_yugen_objects
# ---------------------------------------------------------------------------

class TestClearYugenObjects:
    def test_returns_deleted_count_on_success(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        client.clear_objects = MagicMock(return_value={"deleted_count": 3, "status": "ok"})  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "clear_yugen_objects", {})

        assert isinstance(result, dict)
        assert result["status"] == "ok"
        assert result["deleted_count"] == 3

    def test_returns_zero_when_no_objects(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        client.clear_objects = MagicMock(return_value={"deleted_count": 0, "status": "ok"})  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        result = _call_tool(mcp, "clear_yugen_objects", {})

        assert isinstance(result, dict)
        assert result["deleted_count"] == 0
        assert result["status"] == "ok"

    def test_passes_symbol_to_client_when_provided(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        client.clear_objects = MagicMock(return_value={"deleted_count": 2, "status": "ok"})  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        _call_tool(mcp, "clear_yugen_objects", {"symbol": "EURUSD"})

        call_kwargs = client.clear_objects.call_args.kwargs
        assert call_kwargs.get("symbol") == "EURUSD"

    def test_passes_none_symbol_for_global_clear(self, tmp_path: Path) -> None:
        client = _fake_client(tmp_path)
        client.clear_objects = MagicMock(return_value={"deleted_count": 5, "status": "ok"})  # type: ignore[method-assign]

        mcp = FastMCP(name="test")
        register_chart_tools(mcp, client)
        _call_tool(mcp, "clear_yugen_objects", {})

        call_kwargs = client.clear_objects.call_args.kwargs
        assert call_kwargs.get("symbol") is None
