"""Passive doctor diagnostics primitives and default readiness checks.

This module only performs read-only validation. Doctor checks are diagnostic
observers, not remediation hooks: they must not place orders, reconnect or
repair state on the caller's behalf, mutate account/runtime state, or create
audit directories, SQLite files, or audit rows while producing diagnostics.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast

from .audit import AuditStore
from .config import AppConfig, ConfigError
from .mt5_adapter import MT5Adapter, MT5AdapterError

_REQUIRED_READ_TOOLS = frozenset(
    {
        "list_symbols",
        "get_tick",
        "get_candles",
        "get_account",
        "list_positions",
        "list_orders",
        "get_history",
    }
)


class DoctorStatus(StrEnum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


class DoctorSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(slots=True, frozen=True)
class DoctorCheckResult:
    name: str
    status: DoctorStatus
    severity: DoctorSeverity
    summary: str
    details: Mapping[str, object] = field(default_factory=dict)
    remediation: str | None = None


@dataclass(slots=True, frozen=True)
class DoctorReport:
    status: DoctorStatus
    generated_at: datetime
    checks: list[DoctorCheckResult]


class DoctorCheck(Protocol):
    name: str

    def run(self) -> DoctorCheckResult: ...


class DoctorService:
    def __init__(
        self,
        *,
        checks: Sequence[DoctorCheck],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._checks = tuple(checks)
        self._clock = clock or (lambda: datetime.now(UTC))

    def run(self) -> DoctorReport:
        results = [self._run_check(check) for check in self._checks]
        return DoctorReport(
            status=_overall_status(results),
            generated_at=self._clock(),
            checks=results,
        )

    def _run_check(self, check: DoctorCheck) -> DoctorCheckResult:
        try:
            return check.run()
        except Exception as error:  # pragma: no cover - exercised through service tests
            return DoctorCheckResult(
                name=check.name,
                status=DoctorStatus.FAIL,
                severity=DoctorSeverity.CRITICAL,
                summary=str(error),
                remediation=(
                    "Inspect the failing dependency and retry after the underlying "
                    "issue is fixed."
                ),
            )


def create_default_doctor(
    *,
    config: AppConfig,
    audit_store: AuditStore,
    adapter: MT5Adapter,
    read_tool_names: Sequence[str],
) -> DoctorService:
    checks = cast(
        tuple[DoctorCheck, ...],
        (
            _CallableDoctorCheck("config", lambda: _check_config(config)),
            _CallableDoctorCheck(
                "audit_path",
                lambda: _check_audit_path(audit_store.database_path),
            ),
            _CallableDoctorCheck("mt5_account", lambda: _check_mt5_account(adapter)),
            _CallableDoctorCheck("read_tools", lambda: _check_read_tools(read_tool_names)),
        ),
    )
    return DoctorService(checks=checks)


@dataclass(slots=True, frozen=True)
class _CallableDoctorCheck:
    name: str
    callback: Callable[[], DoctorCheckResult]

    def run(self) -> DoctorCheckResult:
        return self.callback()


def _check_config(config: AppConfig) -> DoctorCheckResult:
    try:
        config.validate_startup()
    except ConfigError as error:
        return DoctorCheckResult(
            name="config",
            status=DoctorStatus.FAIL,
            severity=DoctorSeverity.CRITICAL,
            summary=str(error),
            remediation="Fix the startup configuration before exposing the MCP server.",
        )
    return DoctorCheckResult(
        name="config",
        status=DoctorStatus.OK,
        severity=DoctorSeverity.INFO,
        summary="Configuration startup validation passed.",
    )


def _check_audit_path(path: Path) -> DoctorCheckResult:
    parent = path.parent
    details = {"database_path": str(path), "parent_path": str(parent)}
    if parent.exists() and not parent.is_dir():
        return DoctorCheckResult(
            name="audit_path",
            status=DoctorStatus.FAIL,
            severity=DoctorSeverity.CRITICAL,
            summary="Audit path parent is not a directory.",
            details=details,
            remediation="Point the audit database to a writable directory.",
        )
    if path.exists() and not path.is_file():
        return DoctorCheckResult(
            name="audit_path",
            status=DoctorStatus.FAIL,
            severity=DoctorSeverity.CRITICAL,
            summary="Audit database path is not a file.",
            details=details,
            remediation="Use a filesystem path that resolves to a SQLite file.",
        )
    return DoctorCheckResult(
        name="audit_path",
        status=DoctorStatus.OK,
        severity=DoctorSeverity.INFO,
        summary="Audit path is compatible with lazy SQLite initialization.",
        details=details,
    )


def _check_mt5_account(adapter: MT5Adapter) -> DoctorCheckResult:
    try:
        snapshot = adapter.get_account()
    except MT5AdapterError as error:
        return DoctorCheckResult(
            name="mt5_account",
            status=DoctorStatus.FAIL,
            severity=DoctorSeverity.CRITICAL,
            summary=str(error),
            remediation="Verify MT5 connectivity and account availability.",
        )
    return DoctorCheckResult(
        name="mt5_account",
        status=DoctorStatus.OK,
        severity=DoctorSeverity.INFO,
        summary=f"MT5 account {snapshot.login} on {snapshot.server} is readable.",
        details={"login": snapshot.login, "server": snapshot.server},
    )


def _check_read_tools(read_tool_names: Sequence[str]) -> DoctorCheckResult:
    registered = tuple(read_tool_names)
    missing = sorted(_REQUIRED_READ_TOOLS.difference(registered))
    if missing:
        return DoctorCheckResult(
            name="read_tools",
            status=DoctorStatus.FAIL,
            severity=DoctorSeverity.CRITICAL,
            summary="Required read tools are missing from registration.",
            details={"missing": missing, "registered": list(registered)},
            remediation=(
                "Register every baseline read-only market data tool before enabling "
                "doctor diagnostics."
            ),
        )
    return DoctorCheckResult(
        name="read_tools",
        status=DoctorStatus.OK,
        severity=DoctorSeverity.INFO,
        summary="Baseline read-only tools are registered.",
        details={"registered": list(registered)},
    )


def _overall_status(results: Sequence[DoctorCheckResult]) -> DoctorStatus:
    if any(result.status is DoctorStatus.FAIL for result in results):
        return DoctorStatus.FAIL
    if any(result.status is DoctorStatus.WARN for result in results):
        return DoctorStatus.WARN
    return DoctorStatus.OK
