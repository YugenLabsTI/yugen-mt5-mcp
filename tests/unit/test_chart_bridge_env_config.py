"""TDD tests for parse_chart_bridge_config (Slice C1).

Covers:
- Returns None when YUGEN_MT5_CHART_SHARED_SECRET is unset or blank.
- Returns a valid ChartBridgeConfig when the secret is present.
- Raises ConfigError on non-positive or non-numeric timeout.
- build_runtime does NOT emit chart_bridge_disabled warning when secret is unset (opt-in feature).
- build_runtime does NOT emit the warning when secret is present.
- Doctor status is OK when bridge is disabled (disabled is the normal/default state).
- Importing app.py on Linux does NOT crash (no PipeTransport instantiation at startup).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import pytest

from tests.fakes.fake_mt5 import FakeMT5Backend
from yugen_mt5_mcp.app import (
    CHART_PIPE_NAME_ENV,
    CHART_SHARED_SECRET_ENV,
    CHART_TIMEOUT_ENV,
    build_runtime,
    parse_chart_bridge_config,
)
from yugen_mt5_mcp.chart_bridge import ChartBridgeConfig
from yugen_mt5_mcp.config import ConfigError
from yugen_mt5_mcp.doctor import DoctorService, DoctorStatus
from yugen_mt5_mcp.market_data import MarketDataService
from yugen_mt5_mcp.mt5_adapter import MT5Adapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeServer:
    def run(
        self,
        transport: Literal["stdio", "http", "sse", "streamable-http"] | None = None,
        show_banner: bool | None = None,
        **transport_kwargs: Any,
    ) -> None:
        pass


def _fake_server_factory(
    market_data: MarketDataService, doctor_service: DoctorService
) -> _FakeServer:
    return _FakeServer()


def _adapter_factory() -> MT5Adapter:
    return MT5Adapter(backend=FakeMT5Backend())


# ---------------------------------------------------------------------------
# parse_chart_bridge_config — unit tests (no real transport)
# ---------------------------------------------------------------------------


class TestParseChartBridgeConfig:
    def test_returns_none_when_secret_env_is_missing(self) -> None:
        """No secret env var → bridge disabled → None returned."""
        result = parse_chart_bridge_config({})
        assert result is None

    def test_returns_none_when_secret_env_is_blank(self) -> None:
        """Blank secret (whitespace only) → bridge disabled → None returned."""
        result = parse_chart_bridge_config({CHART_SHARED_SECRET_ENV: "   "})
        assert result is None

    def test_returns_none_when_secret_env_is_empty_string(self) -> None:
        """Empty string secret → bridge disabled → None returned."""
        result = parse_chart_bridge_config({CHART_SHARED_SECRET_ENV: ""})
        assert result is None

    def test_returns_config_when_secret_is_set(self) -> None:
        """Valid secret → returns a ChartBridgeConfig with that secret."""
        result = parse_chart_bridge_config({CHART_SHARED_SECRET_ENV: "my-secret"})
        assert isinstance(result, ChartBridgeConfig)
        assert result.shared_secret == "my-secret"

    def test_default_pipe_name_when_not_specified(self) -> None:
        """Pipe name defaults to 'yugen_chart_bridge' when env var is absent."""
        result = parse_chart_bridge_config({CHART_SHARED_SECRET_ENV: "s3cr3t"})
        assert isinstance(result, ChartBridgeConfig)
        assert result.pipe_name == "yugen_chart_bridge"

    def test_custom_pipe_name_is_accepted(self) -> None:
        """A custom pipe name is used when CHART_PIPE_NAME_ENV is set."""
        result = parse_chart_bridge_config(
            {
                CHART_SHARED_SECRET_ENV: "s3cr3t",
                CHART_PIPE_NAME_ENV: "custom_bridge",
            }
        )
        assert isinstance(result, ChartBridgeConfig)
        assert result.pipe_name == "custom_bridge"

    def test_default_timeout_when_not_specified(self) -> None:
        """Timeout defaults to 1.0 seconds when env var is absent."""
        result = parse_chart_bridge_config({CHART_SHARED_SECRET_ENV: "s3cr3t"})
        assert isinstance(result, ChartBridgeConfig)
        assert result.timeout_seconds == pytest.approx(1.0)

    def test_custom_timeout_is_accepted(self) -> None:
        """A custom positive timeout is accepted."""
        result = parse_chart_bridge_config(
            {
                CHART_SHARED_SECRET_ENV: "s3cr3t",
                CHART_TIMEOUT_ENV: "2.5",
            }
        )
        assert isinstance(result, ChartBridgeConfig)
        assert result.timeout_seconds == pytest.approx(2.5)

    def test_raises_config_error_on_zero_timeout(self) -> None:
        """timeout_seconds=0 must raise ConfigError (fail-loud-at-startup pattern)."""
        with pytest.raises(ConfigError, match="timeout"):
            parse_chart_bridge_config(
                {
                    CHART_SHARED_SECRET_ENV: "s3cr3t",
                    CHART_TIMEOUT_ENV: "0",
                }
            )

    def test_raises_config_error_on_negative_timeout(self) -> None:
        """Negative timeout must raise ConfigError."""
        with pytest.raises(ConfigError, match="timeout"):
            parse_chart_bridge_config(
                {
                    CHART_SHARED_SECRET_ENV: "s3cr3t",
                    CHART_TIMEOUT_ENV: "-1.0",
                }
            )

    def test_raises_config_error_on_non_numeric_timeout(self) -> None:
        """Non-numeric timeout string must raise ConfigError."""
        with pytest.raises(ConfigError, match="timeout"):
            parse_chart_bridge_config(
                {
                    CHART_SHARED_SECRET_ENV: "s3cr3t",
                    CHART_TIMEOUT_ENV: "not-a-number",
                }
            )

    def test_returned_config_passes_internal_validation(self) -> None:
        """The returned ChartBridgeConfig must pass its own validate() method."""
        result = parse_chart_bridge_config({CHART_SHARED_SECRET_ENV: "s3cr3t"})
        assert isinstance(result, ChartBridgeConfig)
        result.validate()  # must not raise


# ---------------------------------------------------------------------------
# build_runtime — chart_bridge_disabled warning integration
# ---------------------------------------------------------------------------


class TestBuildRuntimeChartBridgeWarning:
    def test_no_disabled_warning_when_secret_unset(self, tmp_path: Path) -> None:
        """Disabled bridge is opt-in normal state — must NOT produce a startup warning."""
        runtime = build_runtime(
            env={},
            audit_path=tmp_path / "audit.sqlite3",
            adapter_factory=_adapter_factory,
            server_factory=_fake_server_factory,
        )

        disabled_warnings = [w for w in runtime.warnings if w.code == "chart_bridge_disabled"]
        assert disabled_warnings == [], (
            "chart_bridge_disabled warning must not be emitted: "
            "the chart bridge is opt-in; its absence is the normal default state"
        )

    def test_does_not_emit_disabled_warning_when_secret_is_set(self, tmp_path: Path) -> None:
        """build_runtime does NOT emit chart_bridge_disabled when bridge is enabled."""
        runtime = build_runtime(
            env={CHART_SHARED_SECRET_ENV: "my-secret"},
            audit_path=tmp_path / "audit.sqlite3",
            adapter_factory=_adapter_factory,
            server_factory=_fake_server_factory,
        )

        disabled_warnings = [w for w in runtime.warnings if w.code == "chart_bridge_disabled"]
        assert disabled_warnings == []

    def test_trading_tools_unaffected_when_bridge_disabled(self, tmp_path: Path) -> None:
        """build_runtime succeeds and server is created when bridge is disabled."""
        runtime = build_runtime(
            env={},
            audit_path=tmp_path / "audit.sqlite3",
            adapter_factory=_adapter_factory,
            server_factory=_fake_server_factory,
        )
        # Server must have been created without error.
        assert runtime.server is not None

    def test_app_import_does_not_instantiate_pipe_transport(self) -> None:
        """Importing app on Linux must not crash (PipeTransport is never built at import)."""
        # If we get here, import succeeded. The real guard is that build_runtime
        # does NOT construct ChartBridgeClient at startup on Linux.
        import yugen_mt5_mcp.app as _app  # noqa: F401

        # parse_chart_bridge_config with a secret must return a config (not client).
        config = parse_chart_bridge_config({CHART_SHARED_SECRET_ENV: "s3cr3t"})
        assert isinstance(config, ChartBridgeConfig)
        # No transport is ever constructed here — we just return the config object.


# ---------------------------------------------------------------------------
# Doctor status — chart bridge disabled must NOT degrade to WARN
# ---------------------------------------------------------------------------


class TestDoctorStatusWhenBridgeDisabled:
    def test_doctor_status_ok_when_bridge_disabled_all_else_default(
        self, tmp_path: Path
    ) -> None:
        """Default build (no secret, no risk anomalies) → doctor status must be OK.

        The chart bridge is an opt-in feature. Its normal 'off' state must not
        degrade the overall doctor status to WARN — only genuine anomalies
        (invalid config, unlimited risk limits, wildcard symbols) should do that.
        """
        captured_doctor: DoctorService | None = None

        def capturing_server_factory(
            market_data: MarketDataService, doctor_service: DoctorService
        ) -> _FakeServer:
            nonlocal captured_doctor
            captured_doctor = doctor_service
            return _FakeServer()

        build_runtime(
            env={},
            audit_path=tmp_path / "audit.sqlite3",
            adapter_factory=_adapter_factory,
            server_factory=capturing_server_factory,
        )

        assert captured_doctor is not None
        report = captured_doctor.run()
        assert report.status is DoctorStatus.OK, (
            f"Expected DoctorStatus.OK but got {report.status!r}. "
            f"Checks: {[(c.name, c.status) for c in report.checks]}"
        )

    def test_runtime_warnings_empty_when_bridge_disabled_all_else_default(
        self, tmp_path: Path
    ) -> None:
        """Default build with no secret → runtime.warnings must be empty (no anomalies)."""
        runtime = build_runtime(
            env={},
            audit_path=tmp_path / "audit.sqlite3",
            adapter_factory=_adapter_factory,
            server_factory=_fake_server_factory,
        )

        assert runtime.warnings == (), (
            f"Expected no warnings but got: {runtime.warnings}"
        )
