"""Contract tests for the chart bridge protocol — transport-agnostic.

Uses FakeTransport to run all contract scenarios on Linux CI without Windows / MT5.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.fake_transport import FakeTransport
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(**fields: Any) -> bytes:
    return (json.dumps(fields) + "\n").encode("utf-8")


def build_fake_client(
    tmp_path: Path,
    fake_transport: FakeTransport,
    *,
    pipe_name: str = "test_pipe",
    shared_secret: str = "super-secret",
    timeout_seconds: float = 1.0,
) -> ChartBridgeClient:
    return ChartBridgeClient(
        config=ChartBridgeConfig(
            pipe_name=pipe_name,
            shared_secret=shared_secret,
            timeout_seconds=timeout_seconds,
        ),
        transport=fake_transport,
        audit_store=AuditStore(tmp_path / "audit.sqlite3"),
    )


# ---------------------------------------------------------------------------
# Config validation (formerly socket-based)
# ---------------------------------------------------------------------------

def test_chart_bridge_rejects_empty_pipe_name(tmp_path: Path) -> None:
    """ChartBridgeConfig.validate() must reject an empty pipe_name."""
    with pytest.raises(ValueError, match="pipe_name"):
        ChartBridgeClient(
            config=ChartBridgeConfig(pipe_name="", shared_secret="secret"),
            transport=FakeTransport(response=b""),
            audit_store=AuditStore(tmp_path / "audit.sqlite3"),
        )


# ---------------------------------------------------------------------------
# list_charts
# ---------------------------------------------------------------------------

def test_list_charts_returns_discovery_payload(tmp_path: Path) -> None:
    """list_charts sends the correct envelope and returns chart descriptors."""
    fake = FakeTransport(
        response=_make_response(
            request_id="will-be-replaced",
            action="list_charts",
            status="ok",
            verified=True,
            charts=[
                {"chart_id": 11, "symbol": "EURUSD", "timeframe": "M1"},
                {"chart_id": 12, "symbol": "XAUUSD", "timeframe": "H1"},
            ],
        )
    )
    client = build_fake_client(tmp_path, fake)

    charts = client.list_charts()

    # Verify the request payload
    request = json.loads(fake.last_request.decode("utf-8"))
    assert request["schema_version"] == SCHEMA_VERSION
    assert request["action"] == "list_charts"
    assert request["auth_tag"] == build_auth_tag(
        shared_secret="super-secret",
        schema_version=SCHEMA_VERSION,
        request_id=request["request_id"],
        action="list_charts",
        idempotency_key=request["idempotency_key"],
    )
    # Verify the parsed result
    assert [c.chart_id for c in charts] == [11, 12]
    assert charts[0].symbol == "EURUSD"


# ---------------------------------------------------------------------------
# create_object — happy path
# ---------------------------------------------------------------------------

def test_create_object_requires_verified_ack_and_targets_chart(tmp_path: Path) -> None:
    """create_object sends the correct chart_selector and object payload."""
    # FakeTransport must echo back the request_id and action from the request.
    # We use a callable-style fake that reads from the request.
    sent_requests: list[bytes] = []

    class EchoFakeTransport(FakeTransport):
        def exchange(self, request_line: bytes, *, timeout_seconds: float) -> bytes:
            sent_requests.append(request_line)
            req = json.loads(request_line.decode("utf-8"))
            return _make_response(
                request_id=req["request_id"],
                action=req["action"],
                status="ok",
                verified=True,
                observed_properties={"name": "supply-zone", "color": "red"},
            )

    fake = EchoFakeTransport(response=b"")
    client = build_fake_client(tmp_path, fake)

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
    request = json.loads(sent_requests[0].decode("utf-8"))
    assert request["chart_selector"] == {
        "chart_id": 77,
        "symbol": "eurusd",
        "timeframe": "M5",
    }
    assert request["object"] == {
        "name": "supply-zone",
        "object_type": "TREND",
        "properties": {"color": "red"},
        "points": [
            {"index": 0, "price": 1.101},
            {"index": 1, "price": 1.103},
        ],
    }


# ---------------------------------------------------------------------------
# create_object — unverified ACK
# ---------------------------------------------------------------------------

def test_create_object_rejects_unverified_ack(tmp_path: Path) -> None:
    """Client must raise ChartBridgeProtocolError when ACK has verified=False."""
    sent_requests: list[bytes] = []

    class UnverifiedFakeTransport(FakeTransport):
        def exchange(self, request_line: bytes, *, timeout_seconds: float) -> bytes:
            sent_requests.append(request_line)
            req = json.loads(request_line.decode("utf-8"))
            return _make_response(
                request_id=req["request_id"],
                action=req["action"],
                status="ok",
                verified=False,
            )

    fake = UnverifiedFakeTransport(response=b"")
    client = build_fake_client(tmp_path, fake)

    with pytest.raises(ChartBridgeProtocolError, match="not verified"):
        client.create_object(
            chart=ChartSelector(chart_id=77),
            object_spec=ChartObjectSpec(name="entry", object_type="HLINE"),
        )


# ---------------------------------------------------------------------------
# create_object — timeout
# ---------------------------------------------------------------------------

def test_create_object_times_out_when_service_does_not_reply(tmp_path: Path) -> None:
    """Client must raise ChartBridgeTimeoutError (from transport) and audit as rejected."""
    fake = FakeTransport(
        response=b"irrelevant",
        raises=ChartBridgeTimeoutError("chart bridge request timed out"),
    )
    client = build_fake_client(tmp_path, fake, timeout_seconds=0.05)

    with pytest.raises(ChartBridgeTimeoutError, match="timed out"):
        client.create_object(
            chart=ChartSelector(symbol="EURUSD"),
            object_spec=ChartObjectSpec(name="timeout", object_type="TEXT"),
        )

    rows = AuditStore(tmp_path / "audit.sqlite3").fetch_all()
    assert rows[-1]["event_type"] == "chart_bridge.create_object"
    assert rows[-1]["decision"] == "rejected"
