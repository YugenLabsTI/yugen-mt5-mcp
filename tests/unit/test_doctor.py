from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tests.fakes.fake_mt5 import FakeMT5Backend
from yugen_mt5_mcp.audit import AuditStore
from yugen_mt5_mcp.config import AppConfig, RemoteTransportConfig, TransportConfig, TransportMode
from yugen_mt5_mcp.doctor import (
    DoctorCheckResult,
    DoctorReport,
    DoctorService,
    DoctorSeverity,
    DoctorStatus,
    create_default_doctor,
)
from yugen_mt5_mcp.mt5_adapter import MT5Adapter


@dataclass(slots=True)
class StubCheck:
    name: str
    result: DoctorCheckResult

    def run(self) -> DoctorCheckResult:
        return self.result


@dataclass(slots=True)
class RaisingCheck:
    name: str

    def run(self) -> DoctorCheckResult:
        raise RuntimeError("mt5 unavailable")


def test_doctor_service_aggregates_results_in_registration_order() -> None:
    service = DoctorService(
        checks=(
            StubCheck(
                name="config",
                result=DoctorCheckResult(
                    name="config",
                    status=DoctorStatus.OK,
                    severity=DoctorSeverity.INFO,
                    summary="Configuration is valid",
                ),
            ),
            StubCheck(
                name="read_tools",
                result=DoctorCheckResult(
                    name="read_tools",
                    status=DoctorStatus.FAIL,
                    severity=DoctorSeverity.CRITICAL,
                    summary="Missing read tools",
                ),
            ),
        )
    )

    report = service.run()

    assert isinstance(report, DoctorReport)
    assert report.status is DoctorStatus.FAIL
    assert [check.name for check in report.checks] == ["config", "read_tools"]


def test_doctor_service_converts_check_exceptions_to_failures() -> None:
    service = DoctorService(checks=(RaisingCheck(name="mt5_account"),))

    report = service.run()

    assert report.status is DoctorStatus.FAIL
    assert report.checks[0].name == "mt5_account"
    assert report.checks[0].status is DoctorStatus.FAIL
    assert report.checks[0].severity is DoctorSeverity.CRITICAL
    assert report.checks[0].summary == "mt5 unavailable"


def test_create_default_doctor_reports_healthy_passive_runtime(tmp_path: Path) -> None:
    service = create_default_doctor(
        config=AppConfig(),
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

    assert report.status is DoctorStatus.OK
    assert [check.name for check in report.checks] == [
        "config",
        "audit_path",
        "mt5_account",
        "read_tools",
    ]
    assert all(check.status is DoctorStatus.OK for check in report.checks)


def test_create_default_doctor_reports_degraded_runtime_details(tmp_path: Path) -> None:
    service = create_default_doctor(
        config=AppConfig(
            transport=TransportConfig(
                mode=TransportMode.REMOTE,
                remote=RemoteTransportConfig(enabled=True),
            )
        ),
        audit_store=AuditStore(tmp_path / "missing" / "audit.sqlite3"),
        adapter=MT5Adapter(backend=FakeMT5Backend()),
        read_tool_names=("list_symbols", "get_tick"),
    )

    report = service.run()

    checks = {check.name: check for check in report.checks}
    assert report.status is DoctorStatus.FAIL
    assert checks["config"].status is DoctorStatus.FAIL
    assert checks["audit_path"].status is DoctorStatus.OK
    assert checks["mt5_account"].status is DoctorStatus.OK
    assert checks["read_tools"].status is DoctorStatus.FAIL


def test_create_default_doctor_reports_invalid_audit_parent(tmp_path: Path) -> None:
    audit_parent = tmp_path / "audit-parent"
    audit_parent.write_text("not a directory", encoding="utf-8")

    service = create_default_doctor(
        config=AppConfig(),
        audit_store=AuditStore(audit_parent / "audit.sqlite3"),
        adapter=MT5Adapter(backend=FakeMT5Backend()),
        read_tool_names=(
            "list_symbols",
            "get_tick",
            "get_account",
            "list_positions",
            "list_orders",
            "get_history",
        ),
    )

    checks = {check.name: check for check in service.run().checks}

    assert checks["audit_path"].status is DoctorStatus.FAIL
    assert checks["audit_path"].summary == "Audit path parent is not a directory."
