"""T-16 — Doctor remote-transport posture check (TDD: RED first).

Covers spec S-DOC-01 through S-DOC-06 (§6) and registration in
create_default_doctor.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.fakes.fake_mt5 import FakeMT5Backend
from yugen_mt5_mcp.audit import AuditStore
from yugen_mt5_mcp.config import (
    AppConfig,
    RemoteTransportConfig,
    TransportConfig,
    TransportMode,
)
from yugen_mt5_mcp.doctor import (
    DoctorSeverity,
    DoctorStatus,
    _check_remote_transport,  # type: ignore[attr-defined]
    create_default_doctor,
)
from yugen_mt5_mcp.mt5_adapter import MT5Adapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FULL_READ_TOOLS = (
    "list_symbols",
    "get_tick",
    "get_candles",
    "get_account",
    "list_positions",
    "list_orders",
    "get_history",
)


def _remote_config(**kwargs: object) -> AppConfig:
    """Build an AppConfig with REMOTE transport.  keyword args go into RemoteTransportConfig."""
    remote = RemoteTransportConfig(**kwargs)  # type: ignore[arg-type]
    return AppConfig(
        transport=TransportConfig(
            mode=TransportMode.REMOTE,
            remote=remote,
        )
    )


# ---------------------------------------------------------------------------
# S-DOC-01 — trusted-local, no TLS, no wildcard → clean posture, no warnings
# ---------------------------------------------------------------------------


def test_check_remote_transport_trusted_local_clean() -> None:
    config = _remote_config(
        enabled=True,
        host="127.0.0.1",
        bearer_token="tok",
        tls_terminated=False,
        allowlist=("127.0.0.1/32",),
        allow_insecure=False,
    )

    result = _check_remote_transport(config)

    assert result.name == "remote_transport"
    assert result.status is DoctorStatus.OK
    assert result.severity is DoctorSeverity.INFO
    assert result.details["trust_tier"] == "trusted-local"  # type: ignore[index]
    assert result.details["tls_terminated"] is False  # type: ignore[index]
    assert result.details["warnings"] == []  # type: ignore[index]


# ---------------------------------------------------------------------------
# S-DOC-02 — public, TLS, no wildcard → clean posture, no warnings
# ---------------------------------------------------------------------------


def test_check_remote_transport_public_tls_clean() -> None:
    config = _remote_config(
        enabled=True,
        host="8.8.8.8",
        bearer_token="tok",
        tls_terminated=True,
        allowlist=("8.8.8.0/24",),
        allow_insecure=False,
    )

    result = _check_remote_transport(config)

    assert result.status is DoctorStatus.OK
    assert result.details["trust_tier"] == "public"  # type: ignore[index]
    assert result.details["tls_terminated"] is True  # type: ignore[index]
    assert result.details["warnings"] == []  # type: ignore[index]


# ---------------------------------------------------------------------------
# S-DOC-03 — public, ALLOW_INSECURE → CRITICAL warning ("cleartext" or "INSECURE")
# ---------------------------------------------------------------------------


def test_check_remote_transport_public_allow_insecure_is_critical() -> None:
    config = _remote_config(
        enabled=True,
        host="203.0.113.1",
        bearer_token="tok",
        tls_terminated=False,
        allowlist=("203.0.113.0/24",),
        allow_insecure=True,
    )

    result = _check_remote_transport(config)

    assert result.status is DoctorStatus.FAIL
    assert result.severity is DoctorSeverity.CRITICAL
    warnings = result.details["warnings"]  # type: ignore[index]
    assert len(warnings) >= 1
    combined = " ".join(str(w) for w in warnings).lower()
    assert "cleartext" in combined or "insecure" in combined


# ---------------------------------------------------------------------------
# S-DOC-04 — public, TLS, wildcard allowlist → WARNING
# ---------------------------------------------------------------------------


def test_check_remote_transport_public_tls_wildcard_is_warning() -> None:
    config = _remote_config(
        enabled=True,
        host="8.8.8.8",
        bearer_token="tok",
        tls_terminated=True,
        allowlist=("*",),
        allow_insecure=False,
    )

    result = _check_remote_transport(config)

    assert result.status is DoctorStatus.WARN
    assert result.severity is DoctorSeverity.WARNING
    warnings = result.details["warnings"]  # type: ignore[index]
    assert len(warnings) >= 1
    combined = " ".join(str(w) for w in warnings).lower()
    assert "allowlist is open" in combined or "allowlist" in combined


# ---------------------------------------------------------------------------
# S-DOC-05 — trusted-local, wildcard allowlist → INFO warning
# ---------------------------------------------------------------------------


def test_check_remote_transport_trusted_local_wildcard_is_info() -> None:
    config = _remote_config(
        enabled=True,
        host="127.0.0.1",
        bearer_token="tok",
        tls_terminated=False,
        allowlist=("*",),
        allow_insecure=False,
    )

    result = _check_remote_transport(config)

    # Status stays OK (INFO level), but there is a warning in the details
    assert result.status is DoctorStatus.OK
    assert result.severity is DoctorSeverity.INFO
    warnings = result.details["warnings"]  # type: ignore[index]
    assert len(warnings) >= 1
    combined = " ".join(str(w) for w in warnings).lower()
    assert "allowlist is open" in combined or "allowlist" in combined


# ---------------------------------------------------------------------------
# S-DOC-06 — STDIO mode → no remote-transport posture check in results
# (create_default_doctor does NOT register the check for STDIO mode, OR the
#  check itself returns a skip/OK with mode="stdio" and no remote warnings)
# ---------------------------------------------------------------------------


def test_check_remote_transport_stdio_mode_no_remote_warnings(tmp_path: Path) -> None:
    config = AppConfig()  # default STDIO, remote.enabled=False

    result = _check_remote_transport(config)

    assert result.name == "remote_transport"
    # Stdio → no posture warnings at all
    assert result.details["mode"] == "stdio"  # type: ignore[index]
    assert result.details.get("warnings", []) == []  # type: ignore[index]


# ---------------------------------------------------------------------------
# Registration: remote_transport check appears in create_default_doctor output
# ---------------------------------------------------------------------------


def test_remote_transport_check_registered_in_default_doctor(tmp_path: Path) -> None:
    config = _remote_config(
        enabled=True,
        host="127.0.0.1",
        bearer_token="tok",
        tls_terminated=False,
        allowlist=("127.0.0.1/32",),
    )
    service = create_default_doctor(
        config=config,
        audit_store=AuditStore(tmp_path / "audit.sqlite3"),
        adapter=MT5Adapter(backend=FakeMT5Backend()),
        read_tool_names=_FULL_READ_TOOLS,
    )

    report = service.run()

    check_names = [check.name for check in report.checks]
    assert "remote_transport" in check_names


# ---------------------------------------------------------------------------
# Token must NOT appear in any doctor check output
# ---------------------------------------------------------------------------


def test_check_remote_transport_does_not_expose_bearer_token() -> None:
    secret = "super-secret-token-xyz"
    config = _remote_config(
        enabled=True,
        host="127.0.0.1",
        bearer_token=secret,
        tls_terminated=False,
        allowlist=("127.0.0.1/32",),
    )

    result = _check_remote_transport(config)

    # None of the result fields should contain the raw token value
    import json

    result_json = json.dumps(
        {
            "summary": result.summary,
            "details": dict(result.details),
            "remediation": result.remediation,
        }
    )
    assert secret not in result_json


# ---------------------------------------------------------------------------
# Details fields (S-DOC-01 baseline): required keys present
# ---------------------------------------------------------------------------


def test_check_remote_transport_details_shape() -> None:
    config = _remote_config(
        enabled=True,
        host="127.0.0.1",
        port=9000,
        bearer_token="tok",
        tls_terminated=False,
        allowlist=("127.0.0.1/32",),
        stateless_http=True,
    )

    result = _check_remote_transport(config)

    details = result.details
    assert details["mode"] == "remote"  # type: ignore[index]
    assert details["bind"] == "127.0.0.1:9000"  # type: ignore[index]
    assert details["trust_tier"] in ("trusted-local", "public")  # type: ignore[index]
    assert isinstance(details["tls_terminated"], bool)  # type: ignore[index]
    assert isinstance(details["stateless_http"], bool)  # type: ignore[index]
    assert "allowlist_entries" in details
    assert isinstance(details["warnings"], list)  # type: ignore[index]


# ---------------------------------------------------------------------------
# allowlist_entries reports "*" when wildcard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "allowlist,expected",
    [
        (("127.0.0.1/32",), 1),
        (("127.0.0.1/32", "::1/128"), 2),
        (("*",), "*"),
    ],
)
def test_check_remote_transport_allowlist_entries_value(
    allowlist: tuple[str, ...], expected: object
) -> None:
    config = _remote_config(
        enabled=True,
        host="127.0.0.1",
        bearer_token="tok",
        tls_terminated=False,
        allowlist=allowlist,
    )

    result = _check_remote_transport(config)

    assert result.details["allowlist_entries"] == expected  # type: ignore[index]
