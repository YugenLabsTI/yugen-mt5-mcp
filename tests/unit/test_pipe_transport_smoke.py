"""Smoke test for PipeTransport — skipped on Linux/macOS (Windows only).

On Windows, this test validates a real named-pipe roundtrip using a same-process
server + client thread pair.
"""

from __future__ import annotations

import json
import sys
import threading

import pytest

from yugen_mt5_mcp.chart_bridge import ChartBridgeError


@pytest.mark.skipif(sys.platform != "win32", reason="PipeTransport requires Windows")
def test_pipe_transport_roundtrip_smoke() -> None:  # pragma: no cover
    """Server + client thread round-trip over a real Windows named pipe."""
    from yugen_mt5_mcp.pipe_transport import PipeTransport  # noqa: PLC0415

    pipe_name = "yugen_bridge_smoke_test"
    server = PipeTransport(pipe_name=pipe_name)

    request_payload = json.dumps({"action": "ping", "schema_version": "2026-05-31"}) + "\n"
    response_captured: list[bytes] = []
    server_error: list[Exception] = []

    def run_server() -> None:
        try:
            result = server.exchange(
                request_payload.encode("utf-8"),
                timeout_seconds=5.0,
            )
            response_captured.append(result)
        except Exception as exc:
            server_error.append(exc)

    # Server thread waits for a client connection.
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Client thread connects to the pipe, reads the request, writes back pong.
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    def run_client() -> None:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        pipe_path = f"\\\\.\\pipe\\{pipe_name}"
        # Wait briefly for server to be ready.
        import time  # noqa: PLC0415
        time.sleep(0.05)
        handle = k32.CreateFileW(
            pipe_path,
            0x80000000 | 0x40000000,  # GENERIC_READ | GENERIC_WRITE
            0, None,
            3,   # OPEN_EXISTING
            0, None,
        )
        if handle == ctypes.c_void_p(-1).value:
            return
        # Read the request from server.
        buf = ctypes.create_string_buffer(4096)
        nr = wintypes.DWORD(0)
        k32.ReadFile(handle, buf, 4096, ctypes.byref(nr), None)
        # Write pong response.
        pong = b'{"status": "ok", "pong": true}\n'
        nw = wintypes.DWORD(0)
        k32.WriteFile(handle, ctypes.create_string_buffer(pong), len(pong), ctypes.byref(nw), None)
        k32.FlushFileBuffers(handle)
        k32.CloseHandle(handle)

    client_thread = threading.Thread(target=run_client, daemon=True)
    client_thread.start()

    server_thread.join(timeout=6.0)
    client_thread.join(timeout=6.0)

    assert not server_error, f"Server raised: {server_error[0]}"
    assert response_captured, "Server received no response"
    parsed = json.loads(response_captured[0].decode("utf-8"))
    assert parsed.get("pong") is True


def test_pipe_transport_raises_on_non_windows() -> None:
    """PipeTransport.__init__ must raise ChartBridgeError on Linux/macOS."""
    if sys.platform == "win32":  # pragma: no cover
        pytest.skip("This assertion only applies on non-Windows")
    from yugen_mt5_mcp.pipe_transport import PipeTransport  # noqa: PLC0415

    with pytest.raises(ChartBridgeError, match="Windows"):
        PipeTransport(pipe_name="test")
