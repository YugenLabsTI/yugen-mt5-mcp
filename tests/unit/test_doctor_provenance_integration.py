"""WU-7 — Integration smoke: end-to-end doctor provenance.

Builds a full build_diagnostics(env=..., provenance=...) with a real env dict
and provenance map and asserts that gate check results contain expected source
values.  No FAIL unless config is invalid.
"""
from __future__ import annotations

from pathlib import Path

from yugen_mt5_mcp.app import build_diagnostics
from yugen_mt5_mcp.doctor import DoctorStatus
from yugen_mt5_mcp.provenance import SAFETY_CRITICAL_KEYS, derive_provenance


def test_end_to_end_provenance_env_file_source(tmp_path: Path) -> None:
    """live_trading_gate reflects ENV_FILE source when key comes from file only."""
    file_values = {"YUGEN_MT5_ALLOW_LIVE_TRADING": "true"}
    os_environ: dict[str, str] = {}  # key absent from os.environ

    merged = {**file_values, **os_environ}
    provenance = derive_provenance(file_values, os_environ, SAFETY_CRITICAL_KEYS)

    diagnostics = build_diagnostics(
        env=merged,
        audit_path=tmp_path / "audit.sqlite3",
        provenance=provenance,
    )
    report = diagnostics.doctor.run()

    check_by_name = {c.name: c for c in report.checks}
    assert "live_trading_gate" in check_by_name
    live_check = check_by_name["live_trading_gate"]
    assert live_check.status is DoctorStatus.WARN
    assert live_check.details["source"] == "env-file"


def test_end_to_end_provenance_os_environ_source(tmp_path: Path) -> None:
    """live_trading_gate reflects OS_ENVIRON source when key overrides file."""
    file_values = {"YUGEN_MT5_ALLOW_LIVE_TRADING": "false"}
    os_environ = {"YUGEN_MT5_ALLOW_LIVE_TRADING": "true"}

    merged = {**file_values, **os_environ}
    provenance = derive_provenance(file_values, os_environ, SAFETY_CRITICAL_KEYS)

    diagnostics = build_diagnostics(
        env=merged,
        audit_path=tmp_path / "audit.sqlite3",
        provenance=provenance,
    )
    report = diagnostics.doctor.run()

    check_by_name = {c.name: c for c in report.checks}
    live_check = check_by_name["live_trading_gate"]
    assert live_check.status is DoctorStatus.WARN
    assert live_check.details["source"] == "os.environ"


def test_end_to_end_provenance_all_default(tmp_path: Path) -> None:
    """All gate checks report DEFAULT source when keys absent from both sources."""
    merged: dict[str, str] = {}
    provenance = derive_provenance({}, {}, SAFETY_CRITICAL_KEYS)

    diagnostics = build_diagnostics(
        env=merged,
        audit_path=tmp_path / "audit.sqlite3",
        provenance=provenance,
    )
    report = diagnostics.doctor.run()

    check_by_name = {c.name: c for c in report.checks}
    assert check_by_name["live_trading_gate"].details["source"] == "default"
    assert check_by_name["real_accounts_gate"].details["source"] == "default"
    assert check_by_name["real_account_consent"].details["source"] == "session"


def test_end_to_end_no_fail_when_config_valid(tmp_path: Path) -> None:
    """Full diagnostics run with valid config must not produce any FAIL check."""
    file_values = {"YUGEN_MT5_ALLOW_LIVE_TRADING": "false"}
    os_environ: dict[str, str] = {}

    merged = {**file_values, **os_environ}
    provenance = derive_provenance(file_values, os_environ, SAFETY_CRITICAL_KEYS)

    diagnostics = build_diagnostics(
        env=merged,
        audit_path=tmp_path / "audit.sqlite3",
        provenance=provenance,
    )
    report = diagnostics.doctor.run()

    fail_checks = [c for c in report.checks if c.status is DoctorStatus.FAIL]
    assert fail_checks == [], f"Unexpected FAIL checks: {[c.name for c in fail_checks]}"
