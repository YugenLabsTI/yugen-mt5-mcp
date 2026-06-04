"""Reconnect-strategy tests (slice 2 — T-12 through T-18).

Scenarios covered (per spec):
  S-1  — T-12: lazy reconnect on read: success path
  S-2  — T-13: lazy reconnect on read: backoff budget exhaustion
  S-3  — T-14: unknown error code fails loud without reconnect
  S-4  — T-15: FINANCIAL-SAFETY REGRESSION — send_trade never retries
  S-5,6,7 — T-16: reconnect_mt5 tool success / failure / shape parity
  S-8,9 — T-17: doctor observe-only: healthy + dead states
  S-10,11 — T-18: concurrency lock serialization + stderr log content
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from tests.fakes.fake_mt5 import FakeMT5Backend
from yugen_mt5_mcp.mt5_adapter import (
    STALE_IPC_ERROR_CODES,
    ConnectionState,
    MT5Adapter,
    MT5AdapterError,
    Timeframe,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(backend: FakeMT5Backend) -> MT5Adapter:
    return MT5Adapter(backend=backend)


# ---------------------------------------------------------------------------
# T-12 — S-1: Lazy reconnect on read: success path
# ---------------------------------------------------------------------------


class TestLazyReconnectSuccess:
    def test_read_reconnects_on_stale_ipc(self) -> None:
        """After stale IPC, a read-only call triggers exactly one reconnect."""
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        fake.disconnected = True  # simulate dead IPC

        result = adapter.get_account()

        assert result is not None
        assert fake.reconnect_count == 1

    def test_reconnect_count_unchanged_on_healthy_read(self) -> None:
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)

        adapter.get_account()

        assert fake.reconnect_count == 0

    def test_reconnect_updates_attempts_counter(self) -> None:
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        fake.disconnected = True

        adapter.get_account()

        assert adapter._reconnect_attempts == 1

    def test_reconnect_updates_last_reconnect_at(self) -> None:
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        fake.disconnected = True

        adapter.get_account()

        assert adapter._last_reconnect_at is not None

    def test_connection_state_reflects_reconnect(self) -> None:
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        fake.disconnected = True

        adapter.get_account()  # triggers reconnect
        state = adapter.connection_state()

        assert state.connected is True
        assert state.reconnect_attempts == 1


# ---------------------------------------------------------------------------
# T-13 — S-2: Backoff budget exhaustion
# ---------------------------------------------------------------------------


class TestBackoffExhaustion:
    def test_exhaustion_raises_mt5_adapter_error(self) -> None:
        """When terminal stays down, MT5AdapterError is raised after max attempts."""
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        fake.disconnected = True
        fake.fail_on_reconnect = True

        with pytest.raises(MT5AdapterError, match="unreachable after"):
            adapter.get_account()

    def test_exhaustion_attempts_equals_max(self) -> None:
        """Exactly _RECONNECT_MAX_ATTEMPTS attempts are made before giving up."""
        from yugen_mt5_mcp.mt5_adapter import _RECONNECT_MAX_ATTEMPTS

        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        fake.disconnected = True
        fake.fail_on_reconnect = True

        with pytest.raises(MT5AdapterError):
            adapter.get_account()

        # fail_on_reconnect means initialize() never succeeds, so reconnect_count stays 0
        assert fake.reconnect_count == 0
        # but the adapter-level counter tracks each attempt
        assert adapter._reconnect_attempts == _RECONNECT_MAX_ATTEMPTS

    def test_exhaustion_logs_error_to_stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        fake.disconnected = True
        fake.fail_on_reconnect = True

        with pytest.raises(MT5AdapterError):
            adapter.get_account()

        captured = capsys.readouterr()
        assert "[mt5-reconnect]" in captured.err
        assert "FAILED" in captured.err


# ---------------------------------------------------------------------------
# T-14 — S-3: Unknown error code fails loud, no reconnect
# ---------------------------------------------------------------------------


class TestUnknownErrorCodeFailsLoud:
    def test_unknown_error_does_not_reconnect(self) -> None:
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        # Set a non-stale-IPC error code before making account_info return None
        fake._last_error = (404, "symbol not found")

        def patched_account_info() -> None:
            return None

        fake.account_info = patched_account_info  # type: ignore[method-assign]

        with pytest.raises(MT5AdapterError):
            adapter.get_account()

        assert fake.reconnect_count == 0
        assert adapter._reconnect_attempts == 0

    def test_unknown_error_does_not_touch_stale_ipc_set(self) -> None:
        """Sanity check: the unknown code is genuinely not in the allowlist."""
        assert 404 not in STALE_IPC_ERROR_CODES


# ---------------------------------------------------------------------------
# T-15 — S-4: FINANCIAL-SAFETY REGRESSION — send_trade NEVER retries
# ---------------------------------------------------------------------------


class TestFinancialSafetyBoundary:
    """HARD GATE: send_trade must NEVER trigger a reconnect."""

    def test_send_trade_raises_immediately_without_reconnect(self) -> None:
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        fake.disconnected = True  # IPC is dead

        with pytest.raises(MT5AdapterError):
            adapter.send_trade({"action": 1, "symbol": "EURUSD", "volume": 0.1})

        assert fake.reconnect_count == 0, (
            "FINANCIAL SAFETY VIOLATION: send_trade triggered a reconnect attempt"
        )

    def test_send_trade_does_not_increment_adapter_reconnect_attempts(self) -> None:
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        fake.disconnected = True

        with pytest.raises(MT5AdapterError):
            adapter.send_trade({"action": 1, "symbol": "EURUSD", "volume": 0.1})

        assert adapter._reconnect_attempts == 0

    def test_send_trade_no_retry_even_with_stale_ipc_code(self) -> None:
        """Stale IPC on the write path must still fail loud, not retry."""
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        # disconnected sets _last_error to -10004 (stale IPC) in order_send
        fake.disconnected = True

        with pytest.raises(MT5AdapterError):
            adapter.send_trade({"action": 1, "symbol": "EURUSD", "volume": 0.1})

        # Verify -10004 is a stale-IPC code (so the test is meaningful)
        assert -10004 in STALE_IPC_ERROR_CODES
        # Yet no reconnect
        assert fake.reconnect_count == 0


# ---------------------------------------------------------------------------
# T-16 — S-5, S-6, S-7: reconnect_mt5 tool
# ---------------------------------------------------------------------------


class TestReconnectMT5Tool:
    def test_success_path_returns_connected_state(self) -> None:
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        fake.disconnected = True

        state = adapter.force_reconnect()

        assert isinstance(state, ConnectionState)
        assert state.connected is True
        assert fake.reconnect_count == 1

    def test_success_path_reconnect_attempts_nonzero(self) -> None:
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        fake.disconnected = True

        state = adapter.force_reconnect()

        assert state.reconnect_attempts >= 1

    def test_failure_returns_disconnected_state_not_raises(self) -> None:
        """S-6: terminal still down — must return failure-as-data, never raise."""
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        fake.disconnected = True
        fake.fail_on_reconnect = True

        # Must NOT raise — returns ConnectionState with connected=False
        state = adapter.force_reconnect()

        assert isinstance(state, ConnectionState)
        assert state.connected is False

    def test_shape_parity_with_connection_state(self) -> None:
        """S-7: force_reconnect returns exact same ConnectionState type as connection_state()."""
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)

        probe_state = adapter.connection_state()
        reconnect_state = adapter.force_reconnect()  # already connected

        assert type(probe_state) is type(reconnect_state)
        assert hasattr(probe_state, "connected")
        assert hasattr(probe_state, "last_error_code")
        assert hasattr(probe_state, "last_error_message")
        assert hasattr(probe_state, "reconnect_attempts")
        assert hasattr(probe_state, "last_reconnect_at")


# ---------------------------------------------------------------------------
# T-17 — S-8, S-9: Doctor observe-only
# ---------------------------------------------------------------------------


class TestDoctorObserveOnly:
    def test_healthy_state_reports_connected(self) -> None:
        from yugen_mt5_mcp.doctor import (
            DoctorStatus,
            _check_mt5_connection,
        )

        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)

        result = _check_mt5_connection(adapter)

        assert result.status == DoctorStatus.OK
        assert fake.reconnect_count == 0

    def test_dead_connection_reports_fail(self) -> None:
        from yugen_mt5_mcp.doctor import (
            DoctorStatus,
            _check_mt5_connection,
        )

        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        fake.disconnected = True

        result = _check_mt5_connection(adapter)

        assert result.status == DoctorStatus.FAIL

    def test_doctor_never_reconnects(self) -> None:
        """S-9: doctor must not trigger reconnect even on dead connection."""
        from yugen_mt5_mcp.doctor import _check_mt5_connection

        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        fake.disconnected = True

        _check_mt5_connection(adapter)

        assert fake.reconnect_count == 0, "Doctor must not call reconnect"
        assert adapter._reconnect_attempts == 0

    def test_doctor_dead_reports_stale_ipc_code(self) -> None:
        from yugen_mt5_mcp.doctor import _check_mt5_connection

        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        fake.disconnected = True

        result = _check_mt5_connection(adapter)

        assert "last_error_code" in result.details

    def test_doctor_wired_into_create_default_doctor(self) -> None:
        """REQ-5.6: mt5_connection check appears in default doctor output."""
        from yugen_mt5_mcp.audit import AuditStore
        from yugen_mt5_mcp.config import AppConfig
        from yugen_mt5_mcp.doctor import create_default_doctor

        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        config = AppConfig()
        audit_store = AuditStore(database_path=Path(":memory:"))

        doctor = create_default_doctor(
            config=config,
            audit_store=audit_store,
            adapter=adapter,
            read_tool_names=[
                "list_symbols",
                "get_tick",
                "get_candles",
                "get_account",
                "list_positions",
                "list_orders",
                "get_history",
            ],
        )
        report = doctor.run()
        check_names = [c.name for c in report.checks]
        assert "mt5_connection" in check_names


# ---------------------------------------------------------------------------
# T-18 — S-10, S-11: Concurrency + stderr log content
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_lock_serializes_reconnects(self) -> None:
        """S-10: two concurrent threads; only one reconnect happens."""
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        fake.disconnected = True

        errors: list[Exception] = []
        results: list[object] = []
        barrier = threading.Barrier(2)

        def call_get_account() -> None:
            try:
                barrier.wait()  # release both threads simultaneously
                results.append(adapter.get_account())
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        t1 = threading.Thread(target=call_get_account)
        t2 = threading.Thread(target=call_get_account)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert not errors, f"Thread errors: {errors}"
        # reconnect_count == 1: the second thread reused the reconnected connection
        assert fake.reconnect_count == 1
        assert len(results) == 2

    def test_stderr_logs_attempt_on_reconnect(self, capsys: pytest.CaptureFixture[str]) -> None:
        """S-11: stderr must contain attempt line with trigger, attempt#, error code."""
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        fake.disconnected = True

        adapter.get_account()  # triggers reconnect

        captured = capsys.readouterr()
        err = captured.err
        assert "[mt5-reconnect]" in err
        assert "-10004" in err

    def test_stderr_logs_success_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        """S-11: on success a separate confirmation line must appear."""
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        fake.disconnected = True

        adapter.get_account()

        captured = capsys.readouterr()
        err = captured.err
        assert "reconnected" in err


# ---------------------------------------------------------------------------
# W-1 fix — REQ-2.2: post-reconnect retry-None message must contain
# "after reconnect" (verify-report warning W-1)
# ---------------------------------------------------------------------------


class TestPostReconnectRetryNoneMessage:
    """REQ-2.2: when reconnect succeeds but the retry call still returns None,
    the raised MT5AdapterError message MUST contain 'after reconnect'.

    The first-attempt-failure path (no reconnect) and the unknown-code path
    MUST NOT contain 'after reconnect'.
    """

    def _make_backend_reconnects_but_op_stays_none(
        self,
    ) -> tuple[FakeMT5Backend, list[int]]:
        """Backend where:
        - account_info() returns None with stale IPC on the FIRST call (triggers reconnect).
        - initialize() succeeds (reconnect_count++ and disconnected cleared).
        - account_info() is healthy AFTER reconnect (liveness probe in _reconnect_with_backoff
          must pass — otherwise the backoff loop retries and we never reach the _call path).
        - copy_rates_from_pos() returns None with a non-stale code on every call.
          This is the operation being tested via _call — it triggers reconnect because
          account_info (stale IPC at call time), reconnect succeeds (liveness probe passes),
          but then copy_rates_from_pos STILL returns None → post-reconnect-retry-None path.

        Returns the fake and a counter list [calls_to_rates] for assertions.
        """
        fake = FakeMT5Backend()
        # Simulate stale IPC: account_info returns None -10004 initially.
        fake.disconnected = True

        rates_call_count: list[int] = [0]

        def patched_rates(
            symbol: str, timeframe: int, start_pos: int, count: int
        ) -> None:
            rates_call_count[0] += 1
            # On the FIRST call: disconnected is True so last_error is already -10004 —
            # that triggers the reconnect path in _call.
            # On subsequent calls (after reconnect): still None but non-stale → raises.
            if rates_call_count[0] == 1:
                fake._last_error = (-10004, "No IPC connection")
            else:
                fake._last_error = (0, "no rates data")
            return None

        fake.copy_rates_from_pos = patched_rates  # type: ignore[method-assign]
        return fake, rates_call_count

    def test_post_reconnect_retry_none_message_contains_after_reconnect(self) -> None:
        """_call: post-reconnect retry-None must say 'after reconnect' (REQ-2.2)."""
        fake, rates_calls = self._make_backend_reconnects_but_op_stays_none()
        adapter = _make_adapter(fake)

        with pytest.raises(MT5AdapterError, match="after reconnect"):
            # get_candles → _call → copy_rates_from_pos
            # 1st call: None + stale IPC → reconnect (account_info now works → liveness OK)
            # 2nd call after reconnect: None + non-stale → raises at _call line
            adapter.get_candles("EURUSD", Timeframe.M1, 10)

        # Reconnect DID happen
        assert fake.reconnect_count == 1
        assert rates_calls[0] == 2  # first attempt + one retry

    def test_post_reconnect_retry_none_call_single_message_contains_after_reconnect(
        self,
    ) -> None:
        """_call_single: post-reconnect retry-None must say 'after reconnect' (REQ-2.2)."""
        # symbol_info_tick goes through _call_single.
        # Build a backend where tick returns None with stale IPC on call 1 (reconnect
        # triggered), then reconnect succeeds (account_info healthy), then tick still
        # None on call 2 → post-reconnect-retry-None path in _call_single.
        fake = FakeMT5Backend()
        fake.disconnected = True  # account_info stale initially

        tick_call_count: list[int] = [0]

        def patched_tick(symbol: str) -> None:
            tick_call_count[0] += 1
            if tick_call_count[0] == 1:
                # First call: stale IPC → triggers reconnect
                fake._last_error = (-10004, "No IPC connection")
                return None
            # Second call (after reconnect, account_info healthy): non-stale None
            fake._last_error = (0, "no tick data")
            return None

        fake.symbol_info_tick = patched_tick  # type: ignore[method-assign]
        adapter = _make_adapter(fake)

        with pytest.raises(MT5AdapterError, match="after reconnect"):
            adapter.get_tick("EURUSD")

        assert fake.reconnect_count == 1

    def test_first_attempt_none_no_reconnect_message_does_not_contain_after_reconnect(
        self,
    ) -> None:
        """First-attempt failure (non-stale IPC, no reconnect) must NOT say 'after reconnect'."""
        fake = FakeMT5Backend()
        adapter = _make_adapter(fake)
        # Non-stale error code → no reconnect triggered
        fake._last_error = (404, "symbol not found")

        def patched_account_info() -> None:
            return None

        fake.account_info = patched_account_info  # type: ignore[method-assign]

        with pytest.raises(MT5AdapterError) as exc_info:
            adapter.get_account()

        assert "after reconnect" not in str(exc_info.value)
        assert fake.reconnect_count == 0
