"""Unit tests for ChartBridgeTransport protocol and FakeTransport.

A-1: Verifies the Protocol definition and FakeTransport behavior.
"""

from __future__ import annotations

import pytest

from tests.fakes.fake_transport import FakeTransport
from yugen_mt5_mcp.chart_bridge import (
    ChartBridgeError,
    ChartBridgeTimeoutError,
    ChartBridgeTransport,
)


class TestFakeTransportImplementsProtocol:
    def test_fake_transport_is_runtime_checkable_instance(self) -> None:
        """FakeTransport must satisfy ChartBridgeTransport via structural subtyping."""
        fake = FakeTransport(response=b'{"status": "ok"}\n')
        assert isinstance(fake, ChartBridgeTransport)

    def test_fake_transport_captures_sent_bytes(self) -> None:
        """exchange() must capture the request bytes sent by the client."""
        response = b'{"status": "ok"}\n'
        fake = FakeTransport(response=response)

        result = fake.exchange(b"request-line\n", timeout_seconds=1.0)

        assert fake.last_request == b"request-line\n"
        assert result == b'{"status": "ok"}'  # newline stripped

    def test_fake_transport_strips_trailing_newline(self) -> None:
        """exchange() must strip the trailing newline from the response."""
        fake = FakeTransport(response=b'{"x": 1}\n')
        result = fake.exchange(b"req\n", timeout_seconds=1.0)
        assert result == b'{"x": 1}'

    def test_fake_transport_response_without_newline_returned_as_is(self) -> None:
        """If response has no trailing newline, return it unchanged."""
        fake = FakeTransport(response=b'{"x": 1}')
        result = fake.exchange(b"req\n", timeout_seconds=1.0)
        assert result == b'{"x": 1}'

    def test_fake_transport_raises_timeout_error_on_demand(self) -> None:
        """FakeTransport configured to raise ChartBridgeTimeoutError must do so."""
        fake = FakeTransport(response=b"irrelevant", raises=ChartBridgeTimeoutError("timed out"))
        with pytest.raises(ChartBridgeTimeoutError, match="timed out"):
            fake.exchange(b"req\n", timeout_seconds=1.0)

    def test_fake_transport_raises_chart_bridge_error_on_demand(self) -> None:
        """FakeTransport configured to raise ChartBridgeError must do so."""
        fake = FakeTransport(response=b"irrelevant", raises=ChartBridgeError("connection failed"))
        with pytest.raises(ChartBridgeError, match="connection failed"):
            fake.exchange(b"req\n", timeout_seconds=1.0)

    def test_fake_transport_stores_timeout_seconds(self) -> None:
        """The timeout_seconds kwarg must be passed through and stored."""
        fake = FakeTransport(response=b'{"ok": true}\n')
        fake.exchange(b"req\n", timeout_seconds=2.5)
        assert fake.last_timeout_seconds == 2.5
