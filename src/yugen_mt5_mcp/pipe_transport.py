"""Windows named-pipe SERVER transport for ChartBridgeClient.

The Python side is a pipe SERVER (CreateNamedPipe / ConnectNamedPipe).
The MQL5 Service is the pipe CLIENT (FileOpen on the same path).

Lifecycle per exchange():
  CreateNamedPipeW -> ConnectNamedPipe (overlapped) -> WriteFile(request) ->
  ReadFile loop (overlapped) until newline -> DisconnectNamedPipe -> CloseHandle

Overlapped I/O is used for connect and read so that timeout_seconds is
enforced precisely via WaitForSingleObject.  WriteFile is kept synchronous
because small payloads (< buffer_size) return immediately once they are
queued in the kernel buffer; there is no need to wait for the client to
drain the buffer before returning.

Why FlushFileBuffers was removed
---------------------------------
The original _write() called FlushFileBuffers(handle) after WriteFile.  On a
Windows named pipe, FlushFileBuffers BLOCKS on the SERVER side until the CLIENT
has read all buffered bytes.  In the B-1 probe the MQL5 service never read the
ping, so both sides blocked waiting for the other to drain — a classic deadlock.
WriteFile already queues the bytes in the kernel pipe buffer; the client can
read them at any time without FlushFileBuffers.  Removing it eliminates the
deadlock and keeps latency low.

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

# ---------------------------------------------------------------------------
# Windows API constants
# ---------------------------------------------------------------------------
_PIPE_ACCESS_DUPLEX = 0x00000003
_FILE_FLAG_OVERLAPPED = 0x40000000  # required for non-blocking connect/read
_PIPE_TYPE_BYTE = 0x00000000
_PIPE_READMODE_BYTE = 0x00000000
_PIPE_WAIT = 0x00000000
_NMPWAIT_USE_DEFAULT_WAIT = 0x00000000
# CreateNamedPipeW returns a HANDLE (c_void_p). A failed call yields
# INVALID_HANDLE_VALUE = (HANDLE)-1, which c_void_p surfaces as the
# pointer-width unsigned value (0xFFFF...FFFF) — NOT Python's -1. Compute it
# via c_void_p so the comparison is correct on both Win32 and Win64.
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_ERROR_PIPE_CONNECTED = 535  # client connected before ConnectNamedPipe call
_ERROR_IO_PENDING = 997      # overlapped operation queued, not yet complete
_WAIT_TIMEOUT = 0x00000102   # WaitForSingleObject return value on timeout
_WAIT_FAILED = 0xFFFFFFFF
_INFINITE = 0xFFFFFFFF


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


def _last_error() -> int:
    """Read the ctypes-captured Win32 last error.

    The kernel32 handle is loaded with ``use_last_error=True``, so ctypes swaps
    the real Win32 LastError with its own private copy around every foreign
    call. That private copy MUST be read via ``ctypes.get_last_error`` — calling
    the WinAPI ``GetLastError`` directly returns a stale value.

    Accessed dynamically through ``ctypes.__dict__`` (same pattern as WinDLL
    above) because typeshed guards ``get_last_error`` behind ``win32`` and would
    otherwise fail mypy on Linux; the function exists at runtime regardless.
    """
    return int(ctypes.__dict__["get_last_error"]())


# ---------------------------------------------------------------------------
# OVERLAPPED structure (used for non-blocking I/O)
# ---------------------------------------------------------------------------
# Defined at module level so it can be used in argtypes on Windows.
# The structure layout matches the Windows OVERLAPPED typedef exactly.
class _OVERLAPPED(ctypes.Structure):
    """Minimal OVERLAPPED struct for overlapped (async) WinAPI calls.

    Fields match the Windows SDK OVERLAPPED structure layout.  The hEvent
    field holds the handle of a manual-reset event used by
    WaitForSingleObject to detect I/O completion or timeout.
    """

    # Internal / InternalHigh are ULONG_PTR (pointer-width: 8 bytes on Win64),
    # NOT 32-bit DWORDs. Using c_ulong here undersizes the struct (24 vs 32
    # bytes) and the kernel writes past it → memory corruption. Offset /
    # OffsetHigh are genuine 32-bit DWORDs.
    _fields_ = [
        ("Internal", ctypes.c_void_p),
        ("InternalHigh", ctypes.c_void_p),
        ("Offset", ctypes.c_ulong),
        ("OffsetHigh", ctypes.c_ulong),
        ("hEvent", ctypes.c_void_p),
    ]


class PipeTransport:
    """Named-pipe server transport (Windows only, ctypes/kernel32).

    Uses FILE_FLAG_OVERLAPPED so that ConnectNamedPipe and ReadFile accept
    a timeout rather than blocking indefinitely.  WriteFile is kept
    synchronous (small payloads fit in the kernel buffer and return at once).

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

        # CreateNamedPipeW — open mode now includes FILE_FLAG_OVERLAPPED
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

        # ConnectNamedPipe — second arg is LPOVERLAPPED (pointer to OVERLAPPED)
        k32.ConnectNamedPipe.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_OVERLAPPED),
        ]
        k32.ConnectNamedPipe.restype = wintypes.BOOL

        k32.WriteFile.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        k32.WriteFile.restype = wintypes.BOOL

        # ReadFile — last arg is LPOVERLAPPED
        k32.ReadFile.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(_OVERLAPPED),
        ]
        k32.ReadFile.restype = wintypes.BOOL

        # GetOverlappedResult — retrieves bytes-transferred after an async op
        k32.GetOverlappedResult.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_OVERLAPPED),
            ctypes.POINTER(wintypes.DWORD),
            wintypes.BOOL,
        ]
        k32.GetOverlappedResult.restype = wintypes.BOOL

        # CreateEventW — creates a manual-reset event for WaitForSingleObject
        k32.CreateEventW.argtypes = [
            ctypes.c_void_p,  # lpEventAttributes
            wintypes.BOOL,    # bManualReset
            wintypes.BOOL,    # bInitialState
            wintypes.LPCWSTR, # lpName
        ]
        k32.CreateEventW.restype = wintypes.HANDLE

        # WaitForSingleObject — blocks until event is set or timeout elapses
        k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.WaitForSingleObject.restype = wintypes.DWORD

        # CancelIo — cancels all pending I/O issued by this thread on a handle
        k32.CancelIo.argtypes = [wintypes.HANDLE]
        k32.CancelIo.restype = wintypes.BOOL

        k32.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
        k32.DisconnectNamedPipe.restype = wintypes.BOOL

        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL

        # NOTE: we do NOT bind kernel32.GetLastError. The DLL is loaded with
        # use_last_error=True, so the real Win32 last-error is captured by
        # ctypes and MUST be read via _last_error(). Calling the
        # WinAPI GetLastError() directly returns a stale/garbage value because
        # the foreign-call machinery swaps the error around every call.

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def exchange(self, request_line: bytes, *, timeout_seconds: float) -> bytes:
        """Open the pipe, write request, read response line, close.

        The full operation (connect + write + read) must complete within
        timeout_seconds or ChartBridgeTimeoutError is raised.  The MCP
        layer must never hang indefinitely — this is the "never break
        trading" safety guarantee.

        Raises:
            ChartBridgeTimeoutError: when the deadline is exceeded.
            ChartBridgeError: on pipe creation or I/O failure.
        """
        deadline = time.monotonic() + timeout_seconds
        # --- TEMP latency instrumentation (remove after diagnosis) ----------
        # Splits the round-trip into create/connect/write/read so we can see
        # WHICH phase eats the seconds. Survives the timeout path: the finally
        # block logs whatever phases completed (a missing phase = hung there).
        t_start = time.monotonic()
        marks: dict[str, float] = {}
        # --------------------------------------------------------------------
        handle = self._create_pipe()
        marks["create"] = time.monotonic()
        try:
            self._connect(handle, deadline)
            marks["connect"] = time.monotonic()
            self._write(handle, request_line)
            marks["write"] = time.monotonic()
            response = self._recv_line(handle, deadline)
            marks["read"] = time.monotonic()
            return response
        finally:
            self._log_timing(t_start, marks)  # TEMP instrumentation
            self._k32.DisconnectNamedPipe(handle)
            self._k32.CloseHandle(handle)

    def _log_timing(self, t_start: float, marks: dict[str, float]) -> None:
        """TEMP: emit per-phase latency breakdown to stderr and a temp file.

        Phase deltas are measured from the previous completed mark. A phase
        printed as ``--`` never completed (the exchange raised/timed out there),
        which by itself pinpoints the hanging layer. Remove once the latency
        root cause is found.
        """
        ordered = ("create", "connect", "write", "read")
        parts: list[str] = []
        prev = t_start
        last = t_start
        for name in ordered:
            ts = marks.get(name)
            if ts is None:
                parts.append(f"{name}=--")
                continue
            parts.append(f"{name}={(ts - prev) * 1000:.1f}ms")
            prev = ts
            last = ts
        line = f"[chart-bridge-timing] total={(last - t_start) * 1000:.1f}ms " + " ".join(parts)
        print(line, file=sys.stderr, flush=True)
        try:
            import os  # noqa: PLC0415
            import tempfile  # noqa: PLC0415

            path = os.path.join(tempfile.gettempdir(), "yugen_chart_timing.log")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _create_pipe(self) -> int:
        """Create the named pipe in OVERLAPPED mode.

        FILE_FLAG_OVERLAPPED is ORed into the open-mode so that
        ConnectNamedPipe and ReadFile can be issued as overlapped operations
        and waited on with WaitForSingleObject(event, timeout_ms).
        Without this flag the calls block unconditionally.
        """
        handle = self._k32.CreateNamedPipeW(
            self._pipe_path,
            _PIPE_ACCESS_DUPLEX | _FILE_FLAG_OVERLAPPED,
            _PIPE_TYPE_BYTE | _PIPE_READMODE_BYTE | _PIPE_WAIT,
            1,
            self._buffer_size,
            self._buffer_size,
            _NMPWAIT_USE_DEFAULT_WAIT,
            None,
        )
        if handle == _INVALID_HANDLE_VALUE:
            err = _last_error()
            raise ChartBridgeError(f"CreateNamedPipeW failed: error {err}")
        return int(handle)

    def _make_event(self) -> int:
        """Create a manual-reset, initially non-signalled Win32 event.

        Manual-reset is required so the event stays signalled after
        WaitForSingleObject returns — this lets GetOverlappedResult
        retrieve the byte count without racing against a reset.
        """
        event = self._k32.CreateEventW(None, True, False, None)
        if not event:
            err = _last_error()
            raise ChartBridgeError(f"CreateEventW failed: error {err}")
        return int(event)

    def _deadline_ms(self, deadline: float) -> int:
        """Convert an absolute monotonic deadline to a millisecond timeout.

        Returns 0 if the deadline has already passed (immediate timeout).
        """
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return 0
        return int(remaining * 1000)

    def _connect(self, handle: int, deadline: float) -> None:
        """Wait for the MQL5 client to connect using overlapped I/O.

        Overlapped flow:
        1. Issue ConnectNamedPipe with an OVERLAPPED carrying a manual-reset
           event.  The call returns immediately (ERROR_IO_PENDING) if no
           client has connected yet.
        2. WaitForSingleObject(event, remaining_ms) blocks until the client
           connects OR the deadline elapses.
        3. On WAIT_TIMEOUT: CancelIo + CloseHandle + raise TimeoutError.
        4. ERROR_PIPE_CONNECTED means the client was already there — OK.
        """
        import ctypes.wintypes as wintypes  # noqa: PLC0415

        event_handle = self._make_event()
        try:
            ov = _OVERLAPPED()
            ov.hEvent = event_handle

            ok = self._k32.ConnectNamedPipe(handle, ctypes.byref(ov))
            if ok:
                # Synchronous completion — client was already waiting.
                return

            err = _last_error()
            if err == _ERROR_PIPE_CONNECTED:
                # Client connected before ConnectNamedPipe was called.
                return
            if err != _ERROR_IO_PENDING:
                raise ChartBridgeError(f"ConnectNamedPipe failed: error {err}")

            # I/O is pending — wait up to the remaining deadline.
            timeout_ms = self._deadline_ms(deadline)
            wait_result = self._k32.WaitForSingleObject(event_handle, timeout_ms)
            if wait_result == _WAIT_TIMEOUT:
                self._k32.CancelIo(handle)
                raise ChartBridgeTimeoutError("chart bridge request timed out (connect)")
            if wait_result == _WAIT_FAILED:
                err = _last_error()
                raise ChartBridgeError(f"WaitForSingleObject failed: error {err}")

            # Confirm the overlapped operation succeeded.
            bytes_transferred = wintypes.DWORD(0)
            ok = self._k32.GetOverlappedResult(
                handle, ctypes.byref(ov), ctypes.byref(bytes_transferred), False
            )
            if not ok:
                err = _last_error()
                raise ChartBridgeError(f"GetOverlappedResult (connect) failed: error {err}")
        finally:
            self._k32.CloseHandle(event_handle)

    def _write(self, handle: int, data: bytes) -> None:
        """Write data synchronously.

        Small payloads (well under buffer_size = 64 KB) are queued into the
        kernel buffer and WriteFile returns immediately without waiting for
        the client to read.  FlushFileBuffers is intentionally NOT called:
        it would block until the client drains the buffer, which can cause
        a deadlock when the client is slow or temporarily absent.
        """
        import ctypes.wintypes as wintypes  # noqa: PLC0415

        written = wintypes.DWORD(0)
        buf = ctypes.create_string_buffer(data)
        ok = self._k32.WriteFile(handle, buf, len(data), ctypes.byref(written), None)
        if not ok:
            err = _last_error()
            raise ChartBridgeError(f"WriteFile failed: error {err}")

    def _recv_line(self, handle: int, deadline: float) -> bytes:
        """Read bytes from the pipe until a newline is found or deadline exceeded.

        Overlapped flow per chunk:
        1. Issue ReadFile with an OVERLAPPED event.
        2. WaitForSingleObject(event, remaining_ms) — timeout → raise.
        3. GetOverlappedResult to get actual bytes read.
        4. Accumulate chunks; stop when a newline is found.
        """
        import ctypes.wintypes as wintypes  # noqa: PLC0415

        chunks = bytearray()
        read_buf = ctypes.create_string_buffer(4096)

        while True:
            timeout_ms = self._deadline_ms(deadline)
            if timeout_ms == 0:
                raise ChartBridgeTimeoutError("chart bridge request timed out (read)")

            event_handle = self._make_event()
            try:
                ov = _OVERLAPPED()
                ov.hEvent = event_handle
                bytes_read = wintypes.DWORD(0)

                ok = self._k32.ReadFile(
                    handle, read_buf, 4096, ctypes.byref(bytes_read), ctypes.byref(ov)
                )
                if not ok:
                    err = _last_error()
                    if err != _ERROR_IO_PENDING:
                        raise ChartBridgeError(f"ReadFile failed: error {err}")

                    # Wait for data or timeout.
                    wait_result = self._k32.WaitForSingleObject(event_handle, timeout_ms)
                    if wait_result == _WAIT_TIMEOUT:
                        self._k32.CancelIo(handle)
                        raise ChartBridgeTimeoutError(
                            "chart bridge request timed out (read)"
                        )
                    if wait_result == _WAIT_FAILED:
                        err = _last_error()
                        raise ChartBridgeError(f"WaitForSingleObject failed: error {err}")

                    # Retrieve actual bytes transferred.
                    ok = self._k32.GetOverlappedResult(
                        handle, ctypes.byref(ov), ctypes.byref(bytes_read), False
                    )
                    if not ok:
                        err = _last_error()
                        raise ChartBridgeError(
                            f"GetOverlappedResult (read) failed: error {err}"
                        )

                n = bytes_read.value
            finally:
                self._k32.CloseHandle(event_handle)

            if n == 0:
                break
            chunks.extend(read_buf.raw[:n])
            if b"\n" in chunks:
                break

        line, *_ = bytes(chunks).split(b"\n", 1)
        return line
