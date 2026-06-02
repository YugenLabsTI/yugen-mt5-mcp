"""Windows named-pipe SERVER transport for ChartBridgeClient.

The Python side is a pipe SERVER (CreateNamedPipe / ConnectNamedPipe).
The MQL5 Service is the pipe CLIENT (FileOpen on the same path).

Lifecycle per exchange():
  CreateNamedPipeW -> ConnectNamedPipe -> WriteFile(request) ->
  ReadFile loop until newline -> DisconnectNamedPipe -> CloseHandle

This mirrors the old connect-per-request socket model, which keeps
reconnect and idempotency trivial.

Import safety:
  - Do NOT access ctypes.WinDLL at module level.
  - All Windows API calls are lazy-initialised in __init__().
  - Importing this module on Linux/macOS is safe; only instantiation fails.
"""

from __future__ import annotations

import ctypes
import sys
import time
from typing import Any

from .chart_bridge import ChartBridgeError, ChartBridgeTimeoutError

# Windows API constants — defined here to avoid importing winreg / pywin32.
_PIPE_ACCESS_DUPLEX = 0x00000003
_PIPE_TYPE_BYTE = 0x00000000
_PIPE_READMODE_BYTE = 0x00000000
_PIPE_WAIT = 0x00000000
_NMPWAIT_USE_DEFAULT_WAIT = 0x00000000
_INVALID_HANDLE_VALUE = -1
_ERROR_PIPE_CONNECTED = 535


def _load_kernel32() -> Any:
    """Load kernel32.dll via ctypes — only valid on Windows.

    Using a helper function avoids a module-level WinDLL reference that
    mypy and ruff would flag on Linux.
    """
    import importlib  # noqa: PLC0415

    ctypes_mod = importlib.import_module("ctypes")
    # Access WinDLL dynamically so the import succeeds on Linux.
    win_dll_cls = ctypes_mod.__dict__.get("WinDLL")
    if win_dll_cls is None:
        raise ChartBridgeError("named pipe transport requires Windows (ctypes.WinDLL unavailable)")
    return win_dll_cls("kernel32", use_last_error=True)


class PipeTransport:
    """Named-pipe server transport (Windows only, ctypes/kernel32).

    Raises:
        ChartBridgeError: at instantiation when running on non-Windows.
        ChartBridgeTimeoutError: from exchange() when the deadline is exceeded.
        ChartBridgeError: from exchange() on pipe I/O failure.
    """

    def __init__(self, pipe_name: str, buffer_size: int = 65536) -> None:
        if sys.platform != "win32":
            raise ChartBridgeError("named pipe transport requires Windows")
        self._pipe_path: str = f"\\\\.\\pipe\\{pipe_name}"
        self._buffer_size: int = buffer_size
        self._k32: Any = _load_kernel32()
        self._setup_api()

    def _setup_api(self) -> None:
        """Configure ctypes argtypes/restype for the kernel32 calls we use."""
        import ctypes.wintypes as wintypes  # noqa: PLC0415

        k32 = self._k32

        k32.CreateNamedPipeW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        k32.CreateNamedPipeW.restype = wintypes.HANDLE

        k32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        k32.ConnectNamedPipe.restype = wintypes.BOOL

        k32.WriteFile.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        k32.WriteFile.restype = wintypes.BOOL

        k32.ReadFile.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        k32.ReadFile.restype = wintypes.BOOL

        k32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
        k32.FlushFileBuffers.restype = wintypes.BOOL

        k32.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
        k32.DisconnectNamedPipe.restype = wintypes.BOOL

        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL

        k32.GetLastError.argtypes = []
        k32.GetLastError.restype = wintypes.DWORD

    def exchange(self, request_line: bytes, *, timeout_seconds: float) -> bytes:
        """Open the pipe, write request, read response line, close.

        Raises:
            ChartBridgeTimeoutError: when the deadline is exceeded.
            ChartBridgeError: on pipe creation or I/O failure.
        """
        deadline = time.monotonic() + timeout_seconds
        handle = self._create_pipe()
        try:
            self._connect(handle, deadline)
            self._write(handle, request_line)
            return self._recv_line(handle, deadline)
        finally:
            self._k32.DisconnectNamedPipe(handle)
            self._k32.CloseHandle(handle)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _create_pipe(self) -> int:
        handle = self._k32.CreateNamedPipeW(
            self._pipe_path,
            _PIPE_ACCESS_DUPLEX,
            _PIPE_TYPE_BYTE | _PIPE_READMODE_BYTE | _PIPE_WAIT,
            1,
            self._buffer_size,
            self._buffer_size,
            _NMPWAIT_USE_DEFAULT_WAIT,
            None,
        )
        if handle == _INVALID_HANDLE_VALUE:
            err = self._k32.GetLastError()
            raise ChartBridgeError(f"CreateNamedPipeW failed: error {err}")
        return int(handle)

    def _connect(self, handle: int, deadline: float) -> None:
        ok = self._k32.ConnectNamedPipe(handle, None)
        if not ok:
            err = self._k32.GetLastError()
            if err == _ERROR_PIPE_CONNECTED:
                return  # client already connected before ConnectNamedPipe
            if time.monotonic() >= deadline:
                raise ChartBridgeTimeoutError("chart bridge request timed out (connect)")
            raise ChartBridgeError(f"ConnectNamedPipe failed: error {err}")

    def _write(self, handle: int, data: bytes) -> None:
        import ctypes.wintypes as wintypes  # noqa: PLC0415

        written = wintypes.DWORD(0)
        buf = ctypes.create_string_buffer(data)
        ok = self._k32.WriteFile(handle, buf, len(data), ctypes.byref(written), None)
        if not ok:
            err = self._k32.GetLastError()
            raise ChartBridgeError(f"WriteFile failed: error {err}")
        self._k32.FlushFileBuffers(handle)

    def _recv_line(self, handle: int, deadline: float) -> bytes:
        """Read bytes from the pipe until a newline is found or deadline exceeded."""
        import ctypes.wintypes as wintypes  # noqa: PLC0415

        chunks = bytearray()
        read_buf = ctypes.create_string_buffer(4096)
        bytes_read = wintypes.DWORD(0)

        while True:
            if time.monotonic() >= deadline:
                raise ChartBridgeTimeoutError("chart bridge request timed out (read)")
            ok = self._k32.ReadFile(handle, read_buf, 4096, ctypes.byref(bytes_read), None)
            if not ok:
                err = self._k32.GetLastError()
                raise ChartBridgeError(f"ReadFile failed: error {err}")
            n = bytes_read.value
            if n == 0:
                break
            chunks.extend(read_buf.raw[:n])
            if b"\n" in chunks:
                break

        line, *_ = bytes(chunks).split(b"\n", 1)
        return line
