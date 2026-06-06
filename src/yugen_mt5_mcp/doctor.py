"""Passive doctor diagnostics primitives and default readiness checks.

This module only performs read-only validation. Doctor checks are diagnostic
observers, not remediation hooks: they must not place orders, reconnect or
repair state on the caller's behalf, mutate account/runtime state, or create
audit directories, SQLite files, or audit rows while producing diagnostics.
"""

from __future__ import annotations

import ipaddress
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast

from .audit import AuditStore
from .config import AppConfig, ConfigError, TransportMode
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
    SKIPPED = "skipped"


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


class RuntimeWarningLike(Protocol):
    @property
    def code(self) -> str: ...

    @property
    def message(self) -> str: ...


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
    read_tool_names: Sequence[str] | None,
    entrypoint_warnings: Sequence[RuntimeWarningLike] = (),
    include_platform: bool = False,
    skip_mt5: bool = False,
    provenance: Mapping[str, object] | None = None,
) -> DoctorService:
    """Build the default DoctorService with the configured check set.

    Parameters
    ----------
    read_tool_names:
        Sequence of registered MCP tool names for the read_tools check.
        Pass ``None`` to omit the check entirely (CLI doctor path has no server).
    include_platform:
        When True, insert ``_check_platform`` as the very first check.
    skip_mt5:
        When True, replace the mt5_connection and mt5_account checks with
        SKIPPED stubs.  Used by ``build_diagnostics()`` on non-Windows so that
        MT5-specific checks are transparently skipped without importing MetaTrader5.
    """
    # MT5-specific checks: active or SKIPPED stubs depending on skip_mt5.
    if skip_mt5:
        mt5_checks: tuple[DoctorCheck, ...] = cast(
            tuple[DoctorCheck, ...],
            (
                _CallableDoctorCheck(
                    "mt5_connection",
                    lambda: DoctorCheckResult(
                        name="mt5_connection",
                        status=DoctorStatus.SKIPPED,
                        severity=DoctorSeverity.INFO,
                        summary="Non-Windows platform: MT5 connection check skipped.",
                    ),
                ),
                _CallableDoctorCheck(
                    "mt5_account",
                    lambda: DoctorCheckResult(
                        name="mt5_account",
                        status=DoctorStatus.SKIPPED,
                        severity=DoctorSeverity.INFO,
                        summary="Non-Windows platform: MT5 account check skipped.",
                    ),
                ),
            ),
        )
    else:
        mt5_checks = cast(
            tuple[DoctorCheck, ...],
            (
                # REQ-5.6: mt5_connection BEFORE mt5_account — IPC liveness first.
                _CallableDoctorCheck(
                    "mt5_connection", lambda: _check_mt5_connection(adapter)
                ),
                _CallableDoctorCheck("mt5_account", lambda: _check_mt5_account(adapter)),
            ),
        )

    # read_tools check: omitted when None (CLI doctor path has no server).
    read_tools_checks: tuple[DoctorCheck, ...] = cast(
        tuple[DoctorCheck, ...],
        (
            (
                _CallableDoctorCheck(
                    "read_tools", lambda: _check_read_tools(read_tool_names)
                ),
            )
            if read_tool_names is not None
            else ()
        ),
    )

    core_checks: tuple[DoctorCheck, ...] = cast(
        tuple[DoctorCheck, ...],
        (
            _CallableDoctorCheck("config", lambda: _check_config(config)),
            _CallableDoctorCheck(
                "audit_path",
                lambda: _check_audit_path(audit_store.database_path),
            ),
            _CallableDoctorCheck(
                "runtime_context",
                lambda: _check_runtime_context(config, entrypoint_warnings),
            ),
            _CallableDoctorCheck(
                "remote_transport",
                lambda: _check_remote_transport(config),
            ),
            *mt5_checks,
            _CallableDoctorCheck(
                "real_account_consent",
                lambda: _check_real_account_consent(config, provenance),
            ),
            _CallableDoctorCheck(
                "live_trading_gate",
                lambda: _check_live_trading_gate(config, provenance),
            ),
            _CallableDoctorCheck(
                "real_accounts_gate",
                lambda: _check_real_accounts_gate(config, provenance),
            ),
            *read_tools_checks,
        ),
    )
    if include_platform:
        platform_check: tuple[DoctorCheck, ...] = cast(
            tuple[DoctorCheck, ...],
            (_CallableDoctorCheck("platform", _check_platform),),
        )
        checks = platform_check + core_checks
    else:
        checks = core_checks
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


def _check_mt5_connection(adapter: MT5Adapter) -> DoctorCheckResult:
    """Observe-only IPC liveness check (REQ-5.1–5.6).

    Calls ``adapter.connection_state()`` which is read-only and NEVER triggers
    reconnect logic.  This function MUST NOT call ``_reconnect()`` or any
    write/repair operation — see module docstring.
    """
    state = adapter.connection_state()
    if state.connected:
        return DoctorCheckResult(
            name="mt5_connection",
            status=DoctorStatus.OK,
            severity=DoctorSeverity.INFO,
            summary="MT5 IPC connection live.",
            details={
                "reconnect_attempts": state.reconnect_attempts,
                "last_reconnect_at": (
                    state.last_reconnect_at.isoformat() if state.last_reconnect_at else None
                ),
            },
        )
    return DoctorCheckResult(
        name="mt5_connection",
        status=DoctorStatus.FAIL,
        severity=DoctorSeverity.CRITICAL,
        summary=(
            f"MT5 IPC connection is down "
            f"(last_error={state.last_error_code}: {state.last_error_message})."
        ),
        details={
            "last_error_code": state.last_error_code,
            "last_error_message": state.last_error_message,
            "reconnect_attempts": state.reconnect_attempts,
            "last_reconnect_at": (
                state.last_reconnect_at.isoformat() if state.last_reconnect_at else None
            ),
        },
        remediation=(
            "Call reconnect_mt5 to re-establish the IPC connection, then re-run doctor."
        ),
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


def _check_runtime_context(
    config: AppConfig,
    entrypoint_warnings: Sequence[RuntimeWarningLike],
) -> DoctorCheckResult:
    warning_details = [
        {"code": warning.code, "message": warning.message} for warning in entrypoint_warnings
    ]
    details = {
        "transport_mode": config.transport.mode.value,
        "remote_enabled": config.transport.remote.enabled,
        "allowed_symbols": list(config.risk.allowed_symbols),
        "warnings": warning_details,
    }
    if warning_details:
        return DoctorCheckResult(
            name="runtime_context",
            status=DoctorStatus.WARN,
            severity=DoctorSeverity.WARNING,
            summary="Runtime context includes non-blocking warnings.",
            details=details,
        )
    return DoctorCheckResult(
        name="runtime_context",
        status=DoctorStatus.OK,
        severity=DoctorSeverity.INFO,
        summary="Runtime context is configured without non-blocking warnings.",
        details=details,
    )


_CONSENT_KEY = "YUGEN_MT5_REAL_ACCOUNT_CONSENT"
_LIVE_TRADING_KEY = "YUGEN_MT5_ALLOW_LIVE_TRADING"
_REAL_ACCOUNTS_KEY = "YUGEN_MT5_ALLOW_REAL_ACCOUNTS"


def _check_real_account_consent(
    config: AppConfig, provenance: Mapping[str, object] | None = None
) -> DoctorCheckResult:
    """Passive check: emit WARNING when ambient env-var consent is active.

    Real-account consent via environment variable (real_account_consent_env=True)
    means ANY session can place real-money trades without explicit per-session
    human acknowledgement.  This is intentional but must remain visible.
    The check is purely passive — it reads config only, no state mutations.

    When *provenance* is provided, the ``source`` detail key is populated from
    the provenance map.  When absent, ``source`` defaults to ``"os.environ"``
    (consent active) or ``"session"`` (consent not active) to preserve prior
    semantics.
    """
    from .provenance import ConfigSource  # noqa: PLC0415

    if config.risk.real_account_consent_env:
        if provenance is not None:
            source: object = provenance.get(_CONSENT_KEY, ConfigSource.DEFAULT)
        else:
            source = ConfigSource.OS_ENVIRON
        source_value = source.value if isinstance(source, ConfigSource) else str(source)
        summary = (
            f"Real-account trading consent is pre-authorized via environment variable "
            f"(source: {source_value})."
        )
        return DoctorCheckResult(
            name="real_account_consent",
            status=DoctorStatus.WARN,
            severity=DoctorSeverity.WARNING,
            summary=summary,
            details={
                "source": source_value,
                "allow_real_accounts": config.risk.allow_real_accounts,
            },
            remediation=(
                "Remove YUGEN_MT5_REAL_ACCOUNT_CONSENT to require per-session human "
                "acknowledgement before real-money trading operations."
            ),
        )
    return DoctorCheckResult(
        name="real_account_consent",
        status=DoctorStatus.OK,
        severity=DoctorSeverity.INFO,
        summary="Real-account consent requires explicit per-session acknowledgement.",
        details={"source": "session"},
    )


def _check_live_trading_gate(
    config: AppConfig, provenance: Mapping[str, object] | None = None
) -> DoctorCheckResult:
    """Passive check: warn when live trading is enabled, naming the config source.

    Always passive — reads config and provenance only, no state mutations.
    """
    from .provenance import ConfigSource  # noqa: PLC0415

    if provenance is not None:
        source: object = provenance.get(_LIVE_TRADING_KEY, ConfigSource.DEFAULT)
    else:
        source = ConfigSource.DEFAULT
    source_value = source.value if isinstance(source, ConfigSource) else str(source)

    if config.risk.allow_live_trading:
        return DoctorCheckResult(
            name="live_trading_gate",
            status=DoctorStatus.WARN,
            severity=DoctorSeverity.WARNING,
            summary=(
                f"Live trading is enabled (allow_live_trading=true, source: {source_value})."
            ),
            details={"source": source_value, "allow_live_trading": True},
        )
    return DoctorCheckResult(
        name="live_trading_gate",
        status=DoctorStatus.OK,
        severity=DoctorSeverity.INFO,
        summary="Live trading is disabled (demo/backtest only).",
        details={"source": source_value, "allow_live_trading": False},
    )


def _check_real_accounts_gate(
    config: AppConfig, provenance: Mapping[str, object] | None = None
) -> DoctorCheckResult:
    """Passive check: warn when real accounts are enabled, naming the config source.

    Always passive — reads config and provenance only, no state mutations.
    """
    from .provenance import ConfigSource  # noqa: PLC0415

    if provenance is not None:
        source: object = provenance.get(_REAL_ACCOUNTS_KEY, ConfigSource.DEFAULT)
    else:
        source = ConfigSource.DEFAULT
    source_value = source.value if isinstance(source, ConfigSource) else str(source)

    if config.risk.allow_real_accounts:
        return DoctorCheckResult(
            name="real_accounts_gate",
            status=DoctorStatus.WARN,
            severity=DoctorSeverity.WARNING,
            summary=(
                f"Real accounts are enabled (allow_real_accounts=true, source: {source_value})."
            ),
            details={"source": source_value, "allow_real_accounts": True},
        )
    return DoctorCheckResult(
        name="real_accounts_gate",
        status=DoctorStatus.OK,
        severity=DoctorSeverity.INFO,
        summary="Real accounts are disabled.",
        details={"source": source_value, "allow_real_accounts": False},
    )


def _check_remote_transport(config: AppConfig) -> DoctorCheckResult:
    """Passive posture check for the remote-transport configuration.

    Reports trust tier, TLS status, allowlist breadth, and tiered warnings
    without mutating any state or opening any sockets.  Never emits the
    bearer-token value — it is deliberately omitted from all output.
    """
    remote = config.transport.remote

    # Stdio mode — brief summary, no remote-transport warnings.
    if config.transport.mode is not TransportMode.REMOTE or not remote.enabled:
        return DoctorCheckResult(
            name="remote_transport",
            status=DoctorStatus.OK,
            severity=DoctorSeverity.INFO,
            summary="Transport mode is stdio; no remote-transport posture to evaluate.",
            details={"mode": "stdio", "warnings": []},
        )

    # Determine trust tier.
    try:
        bind_ip: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(remote.host)
        from .security import is_trusted_local_bind

        trusted_local = is_trusted_local_bind(bind_ip)
    except ValueError:
        trusted_local = False
    trust_tier = "trusted-local" if trusted_local else "public"

    # Allowlist entries count — report "*" if the wildcard is present.
    allowlist_entries: int | str = (
        "*" if "*" in remote.allowlist else len(remote.allowlist)
    )

    warnings: list[str] = []
    status = DoctorStatus.OK
    severity = DoctorSeverity.INFO

    # Tiered warning rules (spec §6.2).
    if not trusted_local and not remote.tls_terminated and remote.allow_insecure:
        # CRITICAL: public bind, no TLS, ALLOW_INSECURE active.
        warnings.append(
            "INSECURE: public bind without TLS — token is transmitted in cleartext"
        )
        status = DoctorStatus.FAIL
        severity = DoctorSeverity.CRITICAL
    elif not trusted_local and remote.tls_terminated and "*" in remote.allowlist:
        # WARNING: public bind, TLS present, but allowlist is open.
        warnings.append(
            "allowlist is open (*) — any IP may attempt connection; token is the only gate"
        )
        status = DoctorStatus.WARN
        severity = DoctorSeverity.WARNING
    elif trusted_local and "*" in remote.allowlist:
        # INFO: trusted-local bind with open allowlist.
        warnings.append(
            "allowlist is open (*) on trusted-local bind — consider restricting to known CIDRs"
        )
        # Status stays OK / INFO; warning is surfaced in details only.

    details: dict[str, object] = {
        "mode": "remote",
        "bind": f"{remote.host}:{remote.port}",
        "trust_tier": trust_tier,
        "tls_terminated": remote.tls_terminated,
        "stateless_http": remote.stateless_http,
        "allowlist_entries": allowlist_entries,
        "warnings": warnings,
    }

    if status is DoctorStatus.OK and not warnings:
        summary = (
            f"Remote transport posture is healthy "
            f"(bind={remote.host}:{remote.port}, tier={trust_tier})."
        )
    elif status is DoctorStatus.OK and warnings:
        summary = (
            f"Remote transport posture has informational notes "
            f"(bind={remote.host}:{remote.port}, tier={trust_tier})."
        )
    elif status is DoctorStatus.WARN:
        summary = (
            f"Remote transport posture has warnings "
            f"(bind={remote.host}:{remote.port}, tier={trust_tier})."
        )
    else:
        summary = (
            f"Remote transport posture is CRITICAL "
            f"(bind={remote.host}:{remote.port}, tier={trust_tier}): "
            + "; ".join(warnings)
        )

    return DoctorCheckResult(
        name="remote_transport",
        status=status,
        severity=severity,
        summary=summary,
        details=details,
        remediation=(
            "Enable TLS termination via a reverse proxy (Caddy, nginx, cloud LB) "
            "and set YUGEN_MT5_REMOTE_TLS_TERMINATED=true, or restrict to a "
            "trusted-local bind address."
        )
        if status is not DoctorStatus.OK
        else None,
    )


def _overall_status(results: Sequence[DoctorCheckResult]) -> DoctorStatus:
    # SKIPPED results are ignored — they do not count toward FAIL or WARN.
    active = [r for r in results if r.status is not DoctorStatus.SKIPPED]
    if any(r.status is DoctorStatus.FAIL for r in active):
        return DoctorStatus.FAIL
    if any(r.status is DoctorStatus.WARN for r in active):
        return DoctorStatus.WARN
    return DoctorStatus.OK


def _check_platform() -> DoctorCheckResult:
    """Return OK on win32, SKIPPED on every other platform.

    This is always the first check when ``include_platform=True``.  It never
    returns SKIPPED itself — it either confirms the platform is supported (OK)
    or signals that all subsequent MT5 checks should be skipped (SKIPPED).
    """
    if sys.platform == "win32":
        return DoctorCheckResult(
            name="platform",
            status=DoctorStatus.OK,
            severity=DoctorSeverity.INFO,
            summary="Running on Windows — MT5 checks are active.",
        )
    return DoctorCheckResult(
        name="platform",
        status=DoctorStatus.SKIPPED,
        severity=DoctorSeverity.INFO,
        summary="Non-Windows platform: MT5 checks will be skipped.",
        details={"platform": sys.platform},
    )
