"""WU8 — Doctor WARNING for env-var real-account consent (TDD: RED first)."""
from __future__ import annotations

from pathlib import Path

from tests.fakes.fake_mt5 import FakeMT5Backend
from yugen_mt5_mcp.audit import AuditStore
from yugen_mt5_mcp.config import AppConfig, RiskConfig
from yugen_mt5_mcp.doctor import (
    DoctorSeverity,
    DoctorStatus,
    _check_real_account_consent,  # type: ignore[attr-defined]  # private but tested directly
    create_default_doctor,
)
from yugen_mt5_mcp.mt5_adapter import MT5Adapter

# ---------------------------------------------------------------------------
# WU8-T1: env-flag True → WARN status, severity=WARNING, message refs env-var
# (CD-2-a)
# ---------------------------------------------------------------------------


def test_check_real_account_consent_warns_when_env_flag_active() -> None:
    config = AppConfig(risk=RiskConfig(real_account_consent_env=True))

    result = _check_real_account_consent(config)

    assert result.status is DoctorStatus.WARN
    assert result.severity is DoctorSeverity.WARNING
    assert "YUGEN_MT5_REAL_ACCOUNT_CONSENT" in result.summary or (
        result.remediation is not None and "YUGEN_MT5_REAL_ACCOUNT_CONSENT" in result.remediation
    )


# ---------------------------------------------------------------------------
# WU8-T2: env-flag False → check level is NOT WARNING (CD-2-b)
# ---------------------------------------------------------------------------


def test_check_real_account_consent_ok_when_env_flag_off() -> None:
    config = AppConfig(risk=RiskConfig(real_account_consent_env=False))

    result = _check_real_account_consent(config)

    assert result.status is not DoctorStatus.WARN
    assert result.severity is not DoctorSeverity.WARNING


# ---------------------------------------------------------------------------
# WU8-T3: check is passive — no state mutation (CD-2-c)
# Calling it multiple times must not change any observable state.
# ---------------------------------------------------------------------------


def test_check_real_account_consent_is_passive() -> None:
    config_on = AppConfig(risk=RiskConfig(real_account_consent_env=True))
    config_off = AppConfig(risk=RiskConfig(real_account_consent_env=False))

    result_on_1 = _check_real_account_consent(config_on)
    result_on_2 = _check_real_account_consent(config_on)
    result_off_1 = _check_real_account_consent(config_off)
    result_off_2 = _check_real_account_consent(config_off)

    # Same config → same result (no side effects)
    assert result_on_1.status == result_on_2.status
    assert result_off_1.status == result_off_2.status
    # Config is read-only (frozen dataclass) — no mutation possible
    assert config_on.risk.real_account_consent_env is True
    assert config_off.risk.real_account_consent_env is False


# ---------------------------------------------------------------------------
# WU8-T4: check is registered in create_default_doctor and appears in report
# ---------------------------------------------------------------------------


def test_real_account_consent_check_registered_in_default_doctor(tmp_path: Path) -> None:
    config = AppConfig(risk=RiskConfig(real_account_consent_env=True))
    service = create_default_doctor(
        config=config,
        audit_store=AuditStore(tmp_path / "audit.sqlite3"),
        adapter=MT5Adapter(backend=FakeMT5Backend()),
        read_tool_names=(
            "list_symbols",
            "get_tick",
            "get_candles",
            "get_account",
            "list_positions",
            "list_orders",
            "get_history",
        ),
    )

    report = service.run()

    check_names = [check.name for check in report.checks]
    assert "real_account_consent" in check_names

    consent_check = next(c for c in report.checks if c.name == "real_account_consent")
    assert consent_check.status is DoctorStatus.WARN
    assert consent_check.severity is DoctorSeverity.WARNING


# ---------------------------------------------------------------------------
# WU8-T5: existing passive-diagnostics convention preserved (no state mutation)
# Mirrors the enforcement test from the existing doctor test suite.
# ---------------------------------------------------------------------------


def test_real_account_consent_check_does_not_place_orders(tmp_path: Path) -> None:
    backend = FakeMT5Backend()
    config = AppConfig(risk=RiskConfig(real_account_consent_env=True))
    service = create_default_doctor(
        config=config,
        audit_store=AuditStore(tmp_path / "audit.sqlite3"),
        adapter=MT5Adapter(backend=backend),
        read_tool_names=(
            "list_symbols",
            "get_tick",
            "get_candles",
            "get_account",
            "list_positions",
            "list_orders",
            "get_history",
        ),
    )

    service.run()

    assert backend.order_requests == []
