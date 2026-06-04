"""Tests for slice-1 prerequisites: ConnectionState probe, stale-IPC helper,
and FakeMT5Backend disconnected simulation.

Covers:
- T-03: ConnectionState dataclass + connection_state() probe
- T-06: STALE_IPC_ERROR_CODES constant + _is_stale_ipc() helper
- T-11: FakeMT5Backend.disconnected / reconnect_count / fail_on_reconnect
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from tests.fakes.fake_mt5 import FakeMT5Backend
from yugen_mt5_mcp.mt5_adapter import (
    STALE_IPC_ERROR_CODES,
    ConnectionState,
    MT5Adapter,
)

# ---------------------------------------------------------------------------
# T-11: FakeMT5Backend disconnected simulation
# ---------------------------------------------------------------------------


class TestFakeMT5BackendDisconnected:
    def test_disconnected_flag_defaults_to_false(self) -> None:
        fake = FakeMT5Backend()
        assert fake.disconnected is False

    def test_reconnect_count_defaults_to_zero(self) -> None:
        fake = FakeMT5Backend()
        assert fake.reconnect_count == 0

    def test_fail_on_reconnect_defaults_to_false(self) -> None:
        fake = FakeMT5Backend()
        assert fake.fail_on_reconnect is False

    def test_account_info_returns_none_when_disconnected(self) -> None:
        fake = FakeMT5Backend()
        fake.disconnected = True
        assert fake.account_info() is None

    def test_last_error_returns_stale_ipc_code_when_disconnected(self) -> None:
        fake = FakeMT5Backend()
        fake.disconnected = True
        fake.account_info()
        code, detail = fake.last_error()
        assert code in STALE_IPC_ERROR_CODES
        assert detail

    def test_symbols_get_returns_none_when_disconnected(self) -> None:
        fake = FakeMT5Backend()
        fake.disconnected = True
        assert fake.symbols_get() is None

    def test_symbol_info_tick_returns_none_when_disconnected(self) -> None:
        fake = FakeMT5Backend()
        fake.disconnected = True
        assert fake.symbol_info_tick("EURUSD") is None

    def test_copy_rates_from_pos_returns_none_when_disconnected(self) -> None:
        fake = FakeMT5Backend()
        fake.disconnected = True
        assert fake.copy_rates_from_pos("EURUSD", 1, 0, 10) is None

    def test_positions_get_returns_none_when_disconnected(self) -> None:
        fake = FakeMT5Backend()
        fake.disconnected = True
        assert fake.positions_get() is None

    def test_orders_get_returns_none_when_disconnected(self) -> None:
        fake = FakeMT5Backend()
        fake.disconnected = True
        assert fake.orders_get() is None

    def test_order_send_returns_none_when_disconnected(self) -> None:
        fake = FakeMT5Backend()
        fake.disconnected = True
        result = fake.order_send({"action": 1, "symbol": "EURUSD", "volume": 0.1})
        assert result is None

    def test_initialize_increments_reconnect_count_and_clears_disconnected(self) -> None:
        fake = FakeMT5Backend()
        fake.disconnected = True
        result = fake.initialize()
        assert result is True
        assert fake.disconnected is False
        assert fake.reconnect_count == 1

    def test_initialize_fails_and_stays_disconnected_when_fail_on_reconnect(self) -> None:
        fake = FakeMT5Backend()
        fake.disconnected = True
        fake.fail_on_reconnect = True
        result = fake.initialize()
        assert result is False
        assert fake.disconnected is True

    def test_reconnect_count_not_incremented_when_fail_on_reconnect(self) -> None:
        fake = FakeMT5Backend()
        fake.disconnected = True
        fake.fail_on_reconnect = True
        fake.initialize()
        assert fake.reconnect_count == 0

    def test_normal_initialize_does_not_increment_reconnect_count(self) -> None:
        # A fresh initialize (disconnected=False) should not count as a reconnect
        fake = FakeMT5Backend()
        assert fake.disconnected is False
        fake.initialize()
        # reconnect_count should only track reconnect-driven initializations
        # (i.e., when disconnected was True before the call)
        assert fake.reconnect_count == 0


# ---------------------------------------------------------------------------
# T-03: ConnectionState dataclass
# ---------------------------------------------------------------------------


class TestConnectionStateDataclass:
    def test_connection_state_is_frozen(self) -> None:
        state = ConnectionState(
            connected=True,
            last_error_code=0,
            last_error_message="OK",
            reconnect_attempts=0,
            last_reconnect_at=None,
        )
        from dataclasses import FrozenInstanceError

        with pytest.raises(FrozenInstanceError):
            state.connected = False  # type: ignore[misc]

    def test_connection_state_has_expected_fields(self) -> None:
        now = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        state = ConnectionState(
            connected=True,
            last_error_code=0,
            last_error_message="OK",
            reconnect_attempts=3,
            last_reconnect_at=now,
        )
        assert state.connected is True
        assert state.last_error_code == 0
        assert state.last_error_message == "OK"
        assert state.reconnect_attempts == 3
        assert state.last_reconnect_at == now

    def test_connection_state_none_last_reconnect_at(self) -> None:
        state = ConnectionState(
            connected=False,
            last_error_code=-10004,
            last_error_message="No IPC connection",
            reconnect_attempts=0,
            last_reconnect_at=None,
        )
        assert state.last_reconnect_at is None


# ---------------------------------------------------------------------------
# T-03: connection_state() probe on MT5Adapter
# ---------------------------------------------------------------------------


class TestConnectionStateProbe:
    def test_probe_returns_connected_true_when_backend_healthy(self) -> None:
        fake = FakeMT5Backend()
        adapter = MT5Adapter(backend=fake)

        state = adapter.connection_state()

        assert state.connected is True
        assert state.last_error_code == 0
        assert state.reconnect_attempts == 0
        assert state.last_reconnect_at is None

    def test_probe_returns_connected_false_when_backend_disconnected(self) -> None:
        fake = FakeMT5Backend()
        fake.disconnected = True
        adapter = MT5Adapter(backend=fake)

        state = adapter.connection_state()

        assert state.connected is False
        assert state.last_error_code in STALE_IPC_ERROR_CODES

    def test_probe_does_not_trigger_initialize(self) -> None:
        fake = FakeMT5Backend()
        fake.disconnected = True
        adapter = MT5Adapter(backend=fake)

        adapter.connection_state()

        # Observe-only: no reconnect should have happened
        assert fake.reconnect_count == 0
        assert fake.disconnected is True

    def test_probe_reports_reconnect_attempts_from_adapter_state(self) -> None:
        fake = FakeMT5Backend()
        adapter = MT5Adapter(backend=fake)
        # Manually bump internal state to verify probe reflects it
        adapter._reconnect_attempts = 2

        state = adapter.connection_state()

        assert state.reconnect_attempts == 2

    def test_adapter_initializes_reconnect_attempts_to_zero(self) -> None:
        fake = FakeMT5Backend()
        adapter = MT5Adapter(backend=fake)
        assert adapter._reconnect_attempts == 0

    def test_adapter_initializes_last_reconnect_at_to_none(self) -> None:
        fake = FakeMT5Backend()
        adapter = MT5Adapter(backend=fake)
        assert adapter._last_reconnect_at is None


# ---------------------------------------------------------------------------
# T-06: STALE_IPC_ERROR_CODES and _is_stale_ipc() helper
# ---------------------------------------------------------------------------


class TestStaleIpcHelper:
    def test_stale_ipc_error_codes_is_frozenset(self) -> None:
        assert isinstance(STALE_IPC_ERROR_CODES, frozenset)

    def test_stale_ipc_error_codes_contains_minus_10004(self) -> None:
        assert -10004 in STALE_IPC_ERROR_CODES

    def test_is_stale_ipc_returns_true_for_known_code(self) -> None:
        fake = FakeMT5Backend()
        fake._last_error = (-10004, "No IPC connection")
        adapter = MT5Adapter(backend=fake)

        assert adapter._is_stale_ipc() is True

    def test_is_stale_ipc_returns_false_for_unknown_code(self) -> None:
        fake = FakeMT5Backend()
        fake._last_error = (404, "symbol not found")
        adapter = MT5Adapter(backend=fake)

        assert adapter._is_stale_ipc() is False

    def test_is_stale_ipc_returns_false_for_zero_code(self) -> None:
        fake = FakeMT5Backend()
        fake._last_error = (0, "OK")
        adapter = MT5Adapter(backend=fake)

        assert adapter._is_stale_ipc() is False


# ---------------------------------------------------------------------------
# T-01/T-02: Protocol and adapter wiring (type-coverage tests)
# ---------------------------------------------------------------------------


class TestProtocolInitializeShutdown:
    def test_fake_backend_initialize_satisfies_protocol(self) -> None:
        """FakeMT5Backend.initialize() must be present and callable (Protocol compliance)."""
        fake = FakeMT5Backend()
        result = fake.initialize()
        assert result is True

    def test_fake_backend_shutdown_satisfies_protocol(self) -> None:
        """FakeMT5Backend.shutdown() must be present and callable (Protocol compliance)."""
        fake = FakeMT5Backend()
        fake.shutdown()
        assert fake.shutdown_called is True

    def test_adapter_accepts_backend_with_initialize_and_shutdown(self) -> None:
        """MT5Adapter wraps a backend that has initialize/shutdown — no runtime error."""
        fake = FakeMT5Backend()
        adapter = MT5Adapter(backend=fake)
        # Calling connection_state() exercises that the adapter holds a valid backend
        state = adapter.connection_state()
        assert isinstance(state, ConnectionState)


class TestAdapterThreadedIntoServer:
    def _make_market_data(self) -> Any:
        """Build a minimal MarketDataService using a fake adapter."""
        from yugen_mt5_mcp.audit import AuditStore
        from yugen_mt5_mcp.config import (
            AppConfig,
            AuditConfig,
            RiskConfig,
            TransportConfig,
            TransportMode,
        )
        from yugen_mt5_mcp.market_data import MarketDataService
        from yugen_mt5_mcp.mt5_adapter import MT5Adapter

        fake = FakeMT5Backend()
        adapter = MT5Adapter(backend=fake)
        config = AppConfig(
            transport=TransportConfig(mode=TransportMode.STDIO),
            audit=AuditConfig(database_path=":memory:"),  # type: ignore[arg-type]
            risk=RiskConfig(),
        )
        audit_store = AuditStore(database_path=":memory:")
        return MarketDataService(config=config, adapter=adapter, audit_store=audit_store)

    def test_create_server_accepts_adapter_kwarg(self) -> None:
        """create_server must accept an adapter= keyword argument without error."""
        from yugen_mt5_mcp.mt5_adapter import MT5Adapter
        from yugen_mt5_mcp.server import create_server

        fake = FakeMT5Backend()
        adapter = MT5Adapter(backend=fake)
        market_data = self._make_market_data()

        # Should not raise — adapter is threaded through even if not yet used
        server = create_server(market_data, adapter=adapter)
        assert server is not None

    def test_create_server_works_without_adapter_kwarg(self) -> None:
        """Backward-compat: create_server without adapter= still works."""
        from yugen_mt5_mcp.server import create_server

        market_data = self._make_market_data()
        server = create_server(market_data)
        assert server is not None
