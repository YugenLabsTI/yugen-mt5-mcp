"""WU-5 — Gate check logic: provenance source rendering in doctor checks.

TDD: tests written BEFORE the production implementation.
"""
from __future__ import annotations

from pathlib import Path

from tests.fakes.fake_mt5 import FakeMT5Backend
from yugen_mt5_mcp.audit import AuditStore
from yugen_mt5_mcp.config import AppConfig, RiskConfig
from yugen_mt5_mcp.doctor import (
    DoctorStatus,
    _check_live_trading_gate,
    _check_real_account_consent,
    _check_real_accounts_gate,
    create_default_doctor,
)
from yugen_mt5_mcp.mt5_adapter import MT5Adapter
from yugen_mt5_mcp.provenance import ConfigSource

# ---------------------------------------------------------------------------
# T1: live_trading_gate + OS_ENVIRON + True → WARN, details["source"]=="os.environ"
# ---------------------------------------------------------------------------


def test_live_trading_gate_os_environ_true_warns() -> None:
    config = AppConfig(risk=RiskConfig(allow_live_trading=True))
    provenance = {"YUGEN_MT5_ALLOW_LIVE_TRADING": ConfigSource.OS_ENVIRON}

    result = _check_live_trading_gate(config, provenance)

    assert result.status is DoctorStatus.WARN
    assert result.details["source"] == "os.environ"
    assert "os.environ" in result.summary


# ---------------------------------------------------------------------------
# T2: live_trading_gate + ENV_FILE + True → WARN, details["source"]=="env-file"
# ---------------------------------------------------------------------------


def test_live_trading_gate_env_file_true_warns() -> None:
    config = AppConfig(risk=RiskConfig(allow_live_trading=True))
    provenance = {"YUGEN_MT5_ALLOW_LIVE_TRADING": ConfigSource.ENV_FILE}

    result = _check_live_trading_gate(config, provenance)

    assert result.status is DoctorStatus.WARN
    assert result.details["source"] == "env-file"


# ---------------------------------------------------------------------------
# T3: live_trading_gate + DEFAULT + False → OK, details["source"]=="default"
# ---------------------------------------------------------------------------


def test_live_trading_gate_default_false_ok() -> None:
    config = AppConfig(risk=RiskConfig(allow_live_trading=False))
    provenance = {"YUGEN_MT5_ALLOW_LIVE_TRADING": ConfigSource.DEFAULT}

    result = _check_live_trading_gate(config, provenance)

    assert result.status is DoctorStatus.OK
    assert result.details["source"] == "default"


# ---------------------------------------------------------------------------
# T4: real_accounts_gate + OS_ENVIRON + True → WARN
# ---------------------------------------------------------------------------


def test_real_accounts_gate_os_environ_true_warns() -> None:
    config = AppConfig(risk=RiskConfig(allow_real_accounts=True))
    provenance = {"YUGEN_MT5_ALLOW_REAL_ACCOUNTS": ConfigSource.OS_ENVIRON}

    result = _check_real_accounts_gate(config, provenance)

    assert result.status is DoctorStatus.WARN
    assert result.details["source"] == "os.environ"


# ---------------------------------------------------------------------------
# T5: real_accounts_gate + DEFAULT + False → OK
# ---------------------------------------------------------------------------


def test_real_accounts_gate_default_false_ok() -> None:
    config = AppConfig(risk=RiskConfig(allow_real_accounts=False))
    provenance = {"YUGEN_MT5_ALLOW_REAL_ACCOUNTS": ConfigSource.DEFAULT}

    result = _check_real_accounts_gate(config, provenance)

    assert result.status is DoctorStatus.OK
    assert result.details["source"] == "default"


# ---------------------------------------------------------------------------
# T6: real_account_consent + OS_ENVIRON → WARN + details["source"]=="os.environ" + summary names it
# ---------------------------------------------------------------------------


def test_real_account_consent_os_environ_warns_names_source() -> None:
    config = AppConfig(risk=RiskConfig(real_account_consent_env=True))
    provenance = {"YUGEN_MT5_REAL_ACCOUNT_CONSENT": ConfigSource.OS_ENVIRON}

    result = _check_real_account_consent(config, provenance)

    assert result.status is DoctorStatus.WARN
    assert result.details["source"] == "os.environ"
    assert "os.environ" in result.summary


# ---------------------------------------------------------------------------
# T7: real_account_consent provenance=None → existing behavior preserved
# (details has "source" key from reconciliation, no crash)
# ---------------------------------------------------------------------------


def test_real_account_consent_no_provenance_backward_compat() -> None:
    config_on = AppConfig(risk=RiskConfig(real_account_consent_env=True))
    config_off = AppConfig(risk=RiskConfig(real_account_consent_env=False))

    result_on = _check_real_account_consent(config_on, None)
    result_off = _check_real_account_consent(config_off, None)

    assert result_on.status is DoctorStatus.WARN
    assert result_off.status is DoctorStatus.OK
    # "source" key must be present (from reconciliation)
    assert "source" in result_on.details
    assert "source" in result_off.details


# ---------------------------------------------------------------------------
# T8: additive-only — all pre-existing check names still present
# ---------------------------------------------------------------------------


def test_all_preexisting_check_names_still_present(tmp_path: Path) -> None:
    config = AppConfig(risk=RiskConfig())
    service = create_default_doctor(
        config=config,
        audit_store=AuditStore(tmp_path / "audit.sqlite3"),
        adapter=MT5Adapter(backend=FakeMT5Backend()),
        read_tool_names=None,
    )
    report = service.run()
    check_names = {c.name for c in report.checks}

    required_names = {
        "config",
        "audit_path",
        "runtime_context",
        "remote_transport",
        "mt5_connection",
        "mt5_account",
        "real_account_consent",
    }
    for name in required_names:
        assert name in check_names, f"Expected check '{name}' to be present"


# ---------------------------------------------------------------------------
# live_trading_gate + real_accounts_gate registered in create_default_doctor
# ---------------------------------------------------------------------------


def test_live_trading_gate_registered_in_default_doctor(tmp_path: Path) -> None:
    config = AppConfig(risk=RiskConfig(allow_live_trading=True))
    provenance = {"YUGEN_MT5_ALLOW_LIVE_TRADING": ConfigSource.OS_ENVIRON}
    service = create_default_doctor(
        config=config,
        audit_store=AuditStore(tmp_path / "audit.sqlite3"),
        adapter=MT5Adapter(backend=FakeMT5Backend()),
        read_tool_names=None,
        provenance=provenance,
    )
    report = service.run()
    check_names = [c.name for c in report.checks]
    assert "live_trading_gate" in check_names
    assert "real_accounts_gate" in check_names


def test_live_trading_gate_provenance_none_no_crash(tmp_path: Path) -> None:
    """When provenance=None, gate checks must not crash."""
    config = AppConfig(risk=RiskConfig(allow_live_trading=True))
    service = create_default_doctor(
        config=config,
        audit_store=AuditStore(tmp_path / "audit.sqlite3"),
        adapter=MT5Adapter(backend=FakeMT5Backend()),
        read_tool_names=None,
        provenance=None,
    )
    report = service.run()
    check_names = [c.name for c in report.checks]
    assert "live_trading_gate" in check_names
