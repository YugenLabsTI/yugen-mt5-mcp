"""Configurable risk limits via env vars, including an 'unlimited' option.

`max_symbol_exposure` and `max_order_volume` were hardcoded to 1.0 at runtime
(`build_runtime` never read them from the environment). These tests pin the new
env-var parsing, the unlimited sentinel, and the wiring into RiskConfig.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from tests.fakes.fake_mt5 import FakeMT5Backend
from yugen_mt5_mcp.app import (
    MAX_ORDER_VOLUME_ENV,
    MAX_SYMBOL_EXPOSURE_ENV,
    EntrypointWarning,
    build_runtime,
    parse_risk_limit,
)
from yugen_mt5_mcp.config import AppConfig, ConfigError
from yugen_mt5_mcp.doctor import DoctorService
from yugen_mt5_mcp.market_data import MarketDataService
from yugen_mt5_mcp.mt5_adapter import MT5Adapter

_DEFAULT = Decimal("1.0")


# --------------------------------------------------------------------------- #
# parse_risk_limit
# --------------------------------------------------------------------------- #


def test_parse_risk_limit_unset_returns_default_without_warning() -> None:
    value, warning = parse_risk_limit({}, MAX_ORDER_VOLUME_ENV, default=_DEFAULT)

    assert value == _DEFAULT
    assert warning is None


def test_parse_risk_limit_blank_returns_default_without_warning() -> None:
    value, warning = parse_risk_limit(
        {MAX_ORDER_VOLUME_ENV: "   "}, MAX_ORDER_VOLUME_ENV, default=_DEFAULT
    )

    assert value == _DEFAULT
    assert warning is None


def test_parse_risk_limit_explicit_positive_value() -> None:
    value, warning = parse_risk_limit(
        {MAX_SYMBOL_EXPOSURE_ENV: "5.0"}, MAX_SYMBOL_EXPOSURE_ENV, default=_DEFAULT
    )

    assert value == Decimal("5.0")
    assert warning is None


@pytest.mark.parametrize("raw", ["unlimited", "UNLIMITED", "-1", "-2.5"])
def test_parse_risk_limit_unlimited_sentinels_return_none_with_warning(raw: str) -> None:
    value, warning = parse_risk_limit(
        {MAX_SYMBOL_EXPOSURE_ENV: raw}, MAX_SYMBOL_EXPOSURE_ENV, default=_DEFAULT
    )

    assert value is None
    assert warning == EntrypointWarning(
        code="risk_limit_unlimited",
        message=f"{MAX_SYMBOL_EXPOSURE_ENV}=unlimited removes the configured risk limit",
    )


@pytest.mark.parametrize("raw", ["abc", "0", "0.0", "nan", "inf", "Infinity", "-inf", "none"])
def test_parse_risk_limit_rejects_invalid_or_ambiguous_values(raw: str) -> None:
    """0 (silent lockout), nan/inf (non-finite), 'none' (ambiguous) and junk
    must stop startup, not silently default or disable a safety gate."""
    with pytest.raises(ConfigError, match=MAX_ORDER_VOLUME_ENV):
        parse_risk_limit({MAX_ORDER_VOLUME_ENV: raw}, MAX_ORDER_VOLUME_ENV, default=_DEFAULT)


# --------------------------------------------------------------------------- #
# build_runtime wiring
# --------------------------------------------------------------------------- #


def _capture_config_factory(
    sink: list[AppConfig],
) -> object:
    def server_factory(
        market_data: MarketDataService, doctor_service: DoctorService
    ) -> object:
        sink.append(market_data._config)

        class _Server:
            def run(self, *a: object, **k: object) -> None:  # pragma: no cover - unused
                raise AssertionError

        return _Server()

    return server_factory


def test_build_runtime_reads_risk_limits_from_env(tmp_path: Path) -> None:
    configs: list[AppConfig] = []
    runtime = build_runtime(
        env={
            MAX_SYMBOL_EXPOSURE_ENV: "5.0",
            MAX_ORDER_VOLUME_ENV: "2.0",
        },
        audit_path=tmp_path / "audit.sqlite3",
        adapter_factory=lambda: MT5Adapter(backend=FakeMT5Backend()),
        server_factory=_capture_config_factory(configs),  # type: ignore[arg-type]
    )

    assert configs[0].risk.max_symbol_exposure == Decimal("5.0")
    assert configs[0].risk.max_order_volume == Decimal("2.0")
    # chart_bridge_disabled is expected when no secret is set — not a risk concern.
    non_chart_warnings = tuple(w for w in runtime.warnings if w.code != "chart_bridge_disabled")
    assert non_chart_warnings == ()


def test_build_runtime_defaults_risk_limits_when_env_absent(tmp_path: Path) -> None:
    configs: list[AppConfig] = []
    build_runtime(
        env={},
        audit_path=tmp_path / "audit.sqlite3",
        adapter_factory=lambda: MT5Adapter(backend=FakeMT5Backend()),
        server_factory=_capture_config_factory(configs),  # type: ignore[arg-type]
    )

    assert configs[0].risk.max_symbol_exposure == Decimal("1.0")
    assert configs[0].risk.max_order_volume == Decimal("1.0")


def test_build_runtime_unlimited_exposure_sets_none_and_warns(tmp_path: Path) -> None:
    configs: list[AppConfig] = []
    runtime = build_runtime(
        env={MAX_SYMBOL_EXPOSURE_ENV: "unlimited"},
        audit_path=tmp_path / "audit.sqlite3",
        adapter_factory=lambda: MT5Adapter(backend=FakeMT5Backend()),
        server_factory=_capture_config_factory(configs),  # type: ignore[arg-type]
    )

    assert configs[0].risk.max_symbol_exposure is None
    assert (
        EntrypointWarning(
            code="risk_limit_unlimited",
            message=f"{MAX_SYMBOL_EXPOSURE_ENV}=unlimited removes the configured risk limit",
        )
        in runtime.warnings
    )
