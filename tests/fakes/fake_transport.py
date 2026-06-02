"""In-memory transport fake for testing ChartBridgeClient without pipes or sockets."""

from __future__ import annotations

from yugen_mt5_mcp.chart_bridge import ChartBridgeError


class FakeTransport:
    """Configurable in-memory transport implementing ChartBridgeTransport.

    - Captures the most recent request bytes in `last_request`.
    - Returns `response` from exchange(), stripping a trailing newline if present.
    - If `raises` is set, exchange() raises that exception instead of returning.
    - Stores the `timeout_seconds` kwarg in `last_timeout_seconds` for assertion.
    """

    def __init__(
        self,
        response: bytes,
        raises: ChartBridgeError | None = None,
    ) -> None:
        self._response = response
        self._raises = raises
        self.last_request: bytes = b""
        self.last_timeout_seconds: float = 0.0

    def exchange(self, request_line: bytes, *, timeout_seconds: float) -> bytes:
        self.last_request = request_line
        self.last_timeout_seconds = timeout_seconds
        if self._raises is not None:
            raise self._raises
        # Strip trailing newline to match transport contract (adapters return stripped lines).
        raw = self._response
        if raw.endswith(b"\n"):
            raw = raw[:-1]
        return raw
