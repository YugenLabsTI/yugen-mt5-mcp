"""Tests for mt5-stale-ipc-codes bugfix (T-19 through T-21).

Scenarios covered:
  T-19 — IPC allowlist expansion: -10001 (live-confirmed) and the full
          -10001..-10005 family all trigger lazy reconnect.
  T-20 — Non-IPC codes (-1, -4, 404) do NOT trigger reconnect; they fail loud.
  T-21 — per-call attempt label in _reconnect() always starts at 1 regardless
          of the cumulative lifetime counter.
  T-22 — FINANCIAL-SAFETY REGRESSION with new codes: send_trade still never
          retries even when last_error is -10001.
"""

from __future__ import annotations

import pytest

from tests.fakes.fake_mt5 import FakeMT5Backend
from yugen_mt5_mcp.mt5_adapter import (
    STALE_IPC_ERROR_CODES,
    MT5Adapter,
    MT5AdapterError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(backend: FakeMT5Backend) -> MT5Adapter:
    return MT5Adapter(backend=backend)


def _make_backend_with_ipc_error(error_code: int, error_msg: str) -> FakeMT5Backend:
    """Return a FakeMT5Backend whose first account_info() call returns None with the
    given IPC error code, then restores healthy behaviour after initialize() is called.

    This simulates an IPC bridge break for any of the -10001..-10005 codes, not only
    the -10004 that FakeMT5Backend hardcodes in its disconnected path.
    """
    fake = FakeMT5Backend()

    # First call: simulate IPC failure with the target code
    call_count: list[int] = [0]

    def account_info_ipc_error() -> object:
        call_count[0] += 1
        if call_count[0] == 1:
            fake._last_error = (error_code, error_msg)
            return None
        # After reconnect: return healthy data
        return fake.account

    fake.account_info = account_info_ipc_error  # type: ignore[method-assign]

    # Make initialize() behave as a successful reconnect (increments reconnect_count)
    original_initialize = fake.initialize

    def patched_initialize() -> bool:
        # Force disconnected=True so FakeMT5Backend's reconnect-counting logic fires
        was_disconnected = fake.disconnected
        if not was_disconnected:
            fake.disconnected = True
        result = original_initialize()
        return result

    fake.initialize = patched_initialize  # type: ignore[method-assign]

    return fake


# ---------------------------------------------------------------------------
# T-19 — IPC allowlist must contain the full -10001..-10005 family
# ---------------------------------------------------------------------------


class TestIPCAllowlistContents:
    """Verify that STALE_IPC_ERROR_CODES contains the expected range."""

    @pytest.mark.parametrize("code", [-10001, -10002, -10003, -10004, -10005])
    def test_ipc_family_in_allowlist(self, code: int) -> None:
        """-10001..-10005 must all be in STALE_IPC_ERROR_CODES."""
        assert code in STALE_IPC_ERROR_CODES, (
            f"IPC error code {code} must be in STALE_IPC_ERROR_CODES "
            f"(current: {STALE_IPC_ERROR_CODES})"
        )

    def test_allowlist_is_exactly_five_codes(self) -> None:
        """Allowlist must contain exactly the 5 IPC-family codes — nothing more."""
        assert STALE_IPC_ERROR_CODES == frozenset({-10001, -10002, -10003, -10004, -10005})

    @pytest.mark.parametrize("non_ipc_code", [-1, -4, 404])
    def test_non_ipc_codes_not_in_allowlist(self, non_ipc_code: int) -> None:
        """Non-IPC codes must NOT be in the allowlist."""
        assert non_ipc_code not in STALE_IPC_ERROR_CODES


# ---------------------------------------------------------------------------
# T-19 (functional) — -10001 triggers lazy reconnect (live-confirmed code)
# ---------------------------------------------------------------------------


class TestIPCCodeTriggersReconnect:
    """Parametrized: all five IPC codes must trigger lazy reconnect on a read."""

    @pytest.mark.parametrize(
        ("code", "message"),
        [
            (-10001, "IPC send failed"),
            (-10002, "IPC recv failed"),
            (-10003, "IPC init failed"),
            (-10004, "No IPC connection"),
            (-10005, "IPC timeout"),
        ],
    )
    def test_ipc_error_code_triggers_lazy_reconnect(self, code: int, message: str) -> None:
        """A read call whose backend returns None with any IPC-family code triggers reconnect."""
        fake = _make_backend_with_ipc_error(code, message)
        adapter = _make_adapter(fake)

        # Should succeed after reconnect (get_account uses _call_single → account_info)
        result = adapter.get_account()

        assert result is not None, f"get_account() returned None for IPC code {code}"
        assert fake.reconnect_count == 1, (
            f"Expected exactly 1 reconnect for IPC code {code}, got {fake.reconnect_count}"
        )

    def test_ipc_10001_increments_reconnect_attempts(self) -> None:
        """Specific regression for live-confirmed -10001: reconnect_attempts increments."""
        fake = _make_backend_with_ipc_error(-10001, "IPC send failed")
        adapter = _make_adapter(fake)
        adapter.get_account()

        assert adapter._reconnect_attempts == 1


# ---------------------------------------------------------------------------
# T-20 — Non-IPC codes fail loud WITHOUT triggering reconnect
# ---------------------------------------------------------------------------


class TestNonIPCCodeFailsLoud:
    """Non-IPC error codes must fail loud, not trigger reconnect.

    -1 (Terminal: Call failed) was observed with a wrong symbol name in live tests.
    It is a LEGITIMATE operation failure, not a disconnect signal.
    """

    @pytest.mark.parametrize(
        ("code", "message"),
        [
            (-1, "Terminal: Call failed"),
            (-4, "not supported"),
            (404, "symbol not found"),
        ],
    )
    def test_non_ipc_code_raises_without_reconnect(self, code: int, message: str) -> None:
        """Non-IPC code must raise MT5AdapterError without any reconnect attempt."""
        fake = _make_backend_with_ipc_error(code, message)
        adapter = _make_adapter(fake)

        with pytest.raises(MT5AdapterError):
            adapter.get_account()

        assert fake.reconnect_count == 0, (
            f"Expected 0 reconnects for code {code}, got {fake.reconnect_count}"
        )
        assert adapter._reconnect_attempts == 0, (
            f"Expected 0 reconnect_attempts for code {code}, got {adapter._reconnect_attempts}"
        )

    def test_code_minus_one_does_not_trigger_reconnect(self) -> None:
        """Explicit regression: -1 (live-observed wrong-symbol failure) must NEVER reconnect."""
        fake = _make_backend_with_ipc_error(-1, "Terminal: Call failed")
        adapter = _make_adapter(fake)

        with pytest.raises(MT5AdapterError):
            adapter.get_account()

        assert -1 not in STALE_IPC_ERROR_CODES
        assert fake.reconnect_count == 0


# ---------------------------------------------------------------------------
# T-21 — Per-call attempt label always starts at 1 for each reconnect call
# ---------------------------------------------------------------------------


class TestPerCallAttemptLabel:
    """_reconnect() must log attempt=1/MAX for the first internal attempt of EACH
    separate reconnect call, even if the lifetime counter is already > 0.
    """

    def test_first_reconnect_logs_attempt_1(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """First explicit reconnect logs attempt=1/3."""
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        fake.disconnected = True  # triggers reconnect on force_reconnect

        adapter.force_reconnect()

        captured = capsys.readouterr()
        assert "attempt=1/" in captured.err, (
            f"Expected 'attempt=1/' in stderr.\nStderr was:\n{captured.err}"
        )

    def test_second_separate_reconnect_also_logs_attempt_1(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Second separate reconnect also logs attempt=1/3 (not 2/3 from cumulative counter)."""
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)

        # First reconnect: disconnected=True, then auto-cleared by fake.initialize()
        fake.disconnected = True
        adapter.force_reconnect()

        # Simulate second IPC drop
        fake.disconnected = True
        capsys.readouterr()  # clear captured output from first reconnect

        adapter.force_reconnect()

        captured = capsys.readouterr()
        assert "attempt=1/" in captured.err, (
            "Second separate reconnect must also log attempt=1/, "
            f"but stderr was:\n{captured.err}"
        )
        # Cumulative lifetime counter should be >= 2, proving attempts is NOT what's logged
        assert adapter._reconnect_attempts >= 2, (
            "Lifetime counter must be >= 2 after two reconnects "
            f"(was {adapter._reconnect_attempts})"
        )

    def test_reconnect_label_never_exceeds_max_attempts(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Attempt label must stay within 1..MAX_ATTEMPTS range for a single call."""
        from yugen_mt5_mcp.mt5_adapter import _RECONNECT_MAX_ATTEMPTS

        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        fake.disconnected = True
        fake.fail_on_reconnect = True  # exhaust all retries

        adapter.force_reconnect()  # returns ConnectionState (not raises from tool path)

        captured = capsys.readouterr()
        err = captured.err
        # Every attempt= line must be within range 1..MAX_ATTEMPTS
        import re

        attempt_labels = re.findall(r"attempt=(\d+)/", err)
        for label in attempt_labels:
            n = int(label)
            assert 1 <= n <= _RECONNECT_MAX_ATTEMPTS, (
                f"Attempt label {n} is out of range 1..{_RECONNECT_MAX_ATTEMPTS}"
            )


# ---------------------------------------------------------------------------
# T-22 — FINANCIAL-SAFETY REGRESSION with new IPC codes
# send_trade must NEVER retry even for -10001..-10005
# ---------------------------------------------------------------------------


class TestFinancialSafetyWithNewCodes:
    """HARD GATE: send_trade must never reconnect, even for newly-added IPC codes."""

    @pytest.mark.parametrize("ipc_code", [-10001, -10002, -10003, -10004, -10005])
    def test_send_trade_never_retries_for_any_ipc_code(self, ipc_code: int) -> None:
        """send_trade raises immediately for any IPC-family code — no reconnect."""
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        # order_send returns None with the given IPC code
        fake._last_error = (ipc_code, f"IPC error {ipc_code}")

        def order_send_none(request: object) -> None:
            return None

        fake.order_send = order_send_none  # type: ignore[method-assign]

        with pytest.raises(MT5AdapterError):
            adapter.send_trade({"action": 1, "symbol": "EURUSD", "volume": 0.1})

        assert fake.reconnect_count == 0, (
            f"FINANCIAL SAFETY VIOLATION: send_trade triggered reconnect for code {ipc_code}"
        )
        assert adapter._reconnect_attempts == 0, (
            f"FINANCIAL SAFETY: reconnect_attempts must be 0 for code {ipc_code}"
        )
