"""Tests for build_diagnostics() and the Diagnostics dataclass.

Verifies:
1. build_diagnostics() never calls create_server().
2. build_diagnostics() returns a valid Diagnostics with a DoctorService.
3. On non-Windows (sys.platform monkeypatched): MT5 checks are SKIPPED,
   overall result is not FAIL.
4. DoctorStatus.SKIPPED in _overall_status does not cause overall FAIL.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from yugen_mt5_mcp.app import Diagnostics, build_diagnostics
from yugen_mt5_mcp.doctor import (
    DoctorCheckResult,
    DoctorService,
    DoctorSeverity,
    DoctorStatus,
    _overall_status,
)

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_result(name: str, status: DoctorStatus) -> DoctorCheckResult:
    return DoctorCheckResult(
        name=name,
        status=status,
        severity=DoctorSeverity.INFO,
        summary=f"Stub result for {name}",
    )


# ---------------------------------------------------------------------------
# Task 4a: build_diagnostics() must NEVER call create_server()
# ---------------------------------------------------------------------------


def test_build_diagnostics_does_not_call_create_server(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """create_server() must not be invoked by build_diagnostics()."""

    def _raise(*args: object, **kwargs: object) -> None:
        raise AssertionError("create_server() must NOT be called from build_diagnostics()")

    monkeypatch.setattr("yugen_mt5_mcp.app.create_server", _raise)

    result = build_diagnostics(audit_path=tmp_path / "audit.sqlite3")

    assert isinstance(result, Diagnostics)


# ---------------------------------------------------------------------------
# Task 4b: returns valid Diagnostics with a DoctorService
# ---------------------------------------------------------------------------


def test_build_diagnostics_returns_diagnostics_with_doctor_service(
    tmp_path: Path,
) -> None:
    result = build_diagnostics(audit_path=tmp_path / "audit.sqlite3")

    assert isinstance(result, Diagnostics)
    assert isinstance(result.doctor, DoctorService)
    assert isinstance(result.config, object)
    assert isinstance(result.warnings, tuple)


# ---------------------------------------------------------------------------
# Task 4c: non-Windows — MT5 checks SKIPPED, overall not FAIL
# ---------------------------------------------------------------------------


def test_build_diagnostics_non_windows_mt5_checks_are_skipped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """On non-win32, mt5_connection and mt5_account must be SKIPPED."""
    monkeypatch.setattr("sys.platform", "linux")
    # Re-import sys inside doctor at check time — monkeypatch covers module-level sys
    import yugen_mt5_mcp.doctor as doctor_module

    monkeypatch.setattr(doctor_module.sys, "platform", "linux")

    result = build_diagnostics(audit_path=tmp_path / "audit.sqlite3")
    report = result.doctor.run()

    check_by_name = {c.name: c for c in report.checks}

    assert check_by_name["mt5_connection"].status is DoctorStatus.SKIPPED
    assert check_by_name["mt5_account"].status is DoctorStatus.SKIPPED
    assert report.status is not DoctorStatus.FAIL


def test_build_diagnostics_non_windows_overall_not_fail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Overall report must not be FAIL when all non-config checks pass on Linux."""
    import yugen_mt5_mcp.doctor as doctor_module

    monkeypatch.setattr(doctor_module.sys, "platform", "linux")

    result = build_diagnostics(audit_path=tmp_path / "audit.sqlite3")
    report = result.doctor.run()

    assert report.status is not DoctorStatus.FAIL


# ---------------------------------------------------------------------------
# Task 1: _overall_status ignores SKIPPED
# ---------------------------------------------------------------------------


def test_overall_status_skipped_does_not_cause_fail() -> None:
    results = [
        _make_result("config", DoctorStatus.OK),
        _make_result("mt5_connection", DoctorStatus.SKIPPED),
        _make_result("mt5_account", DoctorStatus.SKIPPED),
    ]
    assert _overall_status(results) is DoctorStatus.OK


def test_overall_status_all_skipped_returns_ok() -> None:
    results = [
        _make_result("a", DoctorStatus.SKIPPED),
        _make_result("b", DoctorStatus.SKIPPED),
    ]
    assert _overall_status(results) is DoctorStatus.OK


def test_overall_status_skipped_plus_fail_still_fails() -> None:
    """SKIPPED is ignored, but a real FAIL still propagates."""
    results = [
        _make_result("config", DoctorStatus.FAIL),
        _make_result("mt5_connection", DoctorStatus.SKIPPED),
    ]
    assert _overall_status(results) is DoctorStatus.FAIL


def test_overall_status_skipped_plus_warn_returns_warn() -> None:
    results = [
        _make_result("config", DoctorStatus.WARN),
        _make_result("mt5_connection", DoctorStatus.SKIPPED),
    ]
    assert _overall_status(results) is DoctorStatus.WARN


# ---------------------------------------------------------------------------
# Task 2: platform check presence when include_platform=True
# ---------------------------------------------------------------------------


def test_build_diagnostics_includes_platform_check(
    tmp_path: Path,
) -> None:
    result = build_diagnostics(audit_path=tmp_path / "audit.sqlite3")
    report = result.doctor.run()

    check_names = [c.name for c in report.checks]
    assert "platform" in check_names
    # Platform check must be first
    assert check_names[0] == "platform"


def test_build_diagnostics_platform_check_is_skipped_on_non_windows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import yugen_mt5_mcp.doctor as doctor_module

    monkeypatch.setattr(doctor_module.sys, "platform", "linux")

    result = build_diagnostics(audit_path=tmp_path / "audit.sqlite3")
    report = result.doctor.run()

    platform_check = next(c for c in report.checks if c.name == "platform")
    assert platform_check.status is DoctorStatus.SKIPPED
