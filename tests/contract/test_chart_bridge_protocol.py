from __future__ import annotations

import json
import socketserver
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

import pytest

from yugen_mt5_mcp.audit import AuditStore
from yugen_mt5_mcp.chart_bridge import (
    SCHEMA_VERSION,
    ChartBridgeClient,
    ChartBridgeConfig,
    ChartBridgeProtocolError,
    ChartBridgeTimeoutError,
    ChartObjectPoint,
    ChartObjectSpec,
    ChartSelector,
    build_auth_tag,
)


class ProtocolTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def build_client(tmp_path: Path, *, port: int, timeout_seconds: float = 0.2) -> ChartBridgeClient:
    return ChartBridgeClient(
        config=ChartBridgeConfig(
            host="127.0.0.1",
            port=port,
            shared_secret="super-secret",
            timeout_seconds=timeout_seconds,
        ),
        audit_store=AuditStore(tmp_path / "audit.sqlite3"),
    )


def run_server(
    handler: Callable[[dict[str, Any]], Mapping[str, object] | None],
) -> tuple[ProtocolTCPServer, threading.Thread]:
    class RequestHandler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            raw_line = self.rfile.readline()
            payload = cast(dict[str, Any], json.loads(raw_line.decode("utf-8")))
            response = handler(payload)
            if response is None:
                return
            self.wfile.write((json.dumps(dict(response)) + "\n").encode("utf-8"))

    server = ProtocolTCPServer(("127.0.0.1", 0), RequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_chart_bridge_rejects_non_loopback_host(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="loopback"):
        ChartBridgeClient(
            config=ChartBridgeConfig(host="192.168.1.5", port=18888, shared_secret="secret"),
            audit_store=AuditStore(tmp_path / "audit.sqlite3"),
        )


def test_list_charts_returns_discovery_payload(tmp_path: Path) -> None:
    captured_request: dict[str, Any] = {}

    def handler(payload: dict[str, Any]) -> Mapping[str, object]:
        captured_request.update(payload)
        return {
            "request_id": payload["request_id"],
            "action": payload["action"],
            "status": "ok",
            "verified": True,
            "charts": [
                {"chart_id": 11, "symbol": "EURUSD", "timeframe": "M1"},
                {"chart_id": 12, "symbol": "XAUUSD", "timeframe": "H1"},
            ],
        }

    server, thread = run_server(handler)
    try:
        client = build_client(tmp_path, port=server.server_address[1])

        charts = client.list_charts()

        assert [chart.chart_id for chart in charts] == [11, 12]
        assert captured_request["schema_version"] == SCHEMA_VERSION
        assert captured_request["action"] == "list_charts"
        assert captured_request["auth_tag"] == build_auth_tag(
            shared_secret="super-secret",
            schema_version=SCHEMA_VERSION,
            request_id=str(captured_request["request_id"]),
            action="list_charts",
            idempotency_key=str(captured_request["idempotency_key"]),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_create_object_requires_verified_ack_and_targets_chart(tmp_path: Path) -> None:
    captured_request: dict[str, Any] = {}

    def handler(payload: dict[str, Any]) -> Mapping[str, object]:
        captured_request.update(payload)
        return {
            "request_id": payload["request_id"],
            "action": payload["action"],
            "status": "ok",
            "verified": True,
            "observed_properties": {
                "name": "supply-zone",
                "color": "red",
            },
        }

    server, thread = run_server(handler)
    try:
        client = build_client(tmp_path, port=server.server_address[1])

        ack = client.create_object(
            chart=ChartSelector(chart_id=77, symbol="eurusd", timeframe="m5"),
            object_spec=ChartObjectSpec(
                name="supply-zone",
                object_type="trend",
                properties={"color": "red"},
                points=(
                    ChartObjectPoint(index=0, price=1.101),
                    ChartObjectPoint(index=1, price=1.103),
                ),
            ),
        )

        assert ack.verified is True
        assert captured_request["chart_selector"] == {
            "chart_id": 77,
            "symbol": "EURUSD",
            "timeframe": "M5",
        }
        assert captured_request["object"] == {
            "name": "supply-zone",
            "object_type": "TREND",
            "properties": {"color": "red"},
            "points": [
                {"index": 0, "price": 1.101},
                {"index": 1, "price": 1.103},
            ],
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_create_object_rejects_unverified_ack(tmp_path: Path) -> None:
    def handler(payload: dict[str, Any]) -> Mapping[str, object]:
        return {
            "request_id": payload["request_id"],
            "action": payload["action"],
            "status": "ok",
            "verified": False,
        }

    server, thread = run_server(handler)
    try:
        client = build_client(tmp_path, port=server.server_address[1])

        with pytest.raises(ChartBridgeProtocolError, match="not verified"):
            client.create_object(
                chart=ChartSelector(chart_id=77),
                object_spec=ChartObjectSpec(name="entry", object_type="HLINE"),
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_create_object_times_out_when_service_does_not_reply(tmp_path: Path) -> None:
    def handler(payload: dict[str, Any]) -> None:
        del payload
        time.sleep(0.3)
        return None

    server, thread = run_server(handler)
    try:
        client = build_client(tmp_path, port=server.server_address[1], timeout_seconds=0.05)

        with pytest.raises(ChartBridgeTimeoutError, match="timed out"):
            client.create_object(
                chart=ChartSelector(symbol="EURUSD"),
                object_spec=ChartObjectSpec(name="timeout", object_type="TEXT"),
            )

        rows = AuditStore(tmp_path / "audit.sqlite3").fetch_all()
        assert rows[-1]["event_type"] == "chart_bridge.create_object"
        assert rows[-1]["decision"] == "rejected"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
