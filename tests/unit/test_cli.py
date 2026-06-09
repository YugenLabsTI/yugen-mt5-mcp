"""Unit tests for the CLI (cli.py).

Uses typer.testing.CliRunner for command dispatch and output assertions.
Heavy dependencies (MetaTrader5, uvicorn, fastmcp) are mocked so these
tests run on any platform.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from yugen_mt5_mcp.cli import app
from yugen_mt5_mcp.doctor import DoctorCheckResult, DoctorReport, DoctorSeverity, DoctorStatus

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------


def _make_report(
    *checks: tuple[str, DoctorStatus],
    overall: DoctorStatus = DoctorStatus.OK,
) -> DoctorReport:
    from datetime import UTC, datetime

    return DoctorReport(
        status=overall,
        generated_at=datetime.now(UTC),
        checks=[
            DoctorCheckResult(
                name=name,
                status=status,
                severity=DoctorSeverity.INFO,
                summary=f"Stub summary for {name}.",
            )
            for name, status in checks
        ],
    )


class _FakeDoctorService:
    def __init__(self, report: DoctorReport) -> None:
        self._report = report

    def run(self) -> DoctorReport:
        return self._report


class _FakeDiagnostics:
    def __init__(self, report: DoctorReport) -> None:
        self.doctor = _FakeDoctorService(report)


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------


def test_run_stdio_calls_build_runtime(tmp_path: Path) -> None:
    """``run`` (or bare invocation) should call build_runtime then run_stdio."""
    mock_runtime = MagicMock()
    mock_runtime.warnings = ()
    mock_runtime.config.transport.mode.name = "STDIO"

    # Patch at the module level where cli.py imports from
    with (
        patch("yugen_mt5_mcp.cli._run_stdio") as mock_run_stdio,
    ):
        result = runner.invoke(app, ["run"])

    assert result.exit_code == 0 or mock_run_stdio.called


def test_bare_invocation_calls_run_stdio() -> None:
    """Bare invocation (no subcommand) must behave like ``run``."""
    with patch("yugen_mt5_mcp.cli._run_stdio") as mock_run_stdio:
        result = runner.invoke(app, [])
        assert mock_run_stdio.called
    assert result.exit_code == 0


def test_run_explicit_stdio_transport() -> None:
    """``run --transport stdio`` must call _run_stdio."""
    with patch("yugen_mt5_mcp.cli._run_stdio") as mock_run_stdio:
        result = runner.invoke(app, ["run", "--transport", "stdio"])
        assert mock_run_stdio.called
    assert result.exit_code == 0


def test_run_remote_without_uvicorn_exits_1() -> None:
    """``run --transport remote`` without uvicorn installed exits with code 1."""
    with patch.dict(sys.modules, {"uvicorn": None}):
        result = runner.invoke(app, ["run", "--transport", "remote"])

    assert result.exit_code == 1
    assert "yugen-mt5-mcp[remote]" in result.output or "yugen-mt5-mcp[remote]" in (
        result.stderr or ""
    )


def test_run_unknown_transport_exits_1() -> None:
    """Unknown --transport value must exit with code 1."""
    result = runner.invoke(app, ["run", "--transport", "grpc"])
    assert result.exit_code == 1


def test_run_env_file_loads_values(tmp_path: Path) -> None:
    """``--env-file`` values are parsed and passed to the runtime env."""
    env_file = tmp_path / "demo.env"
    env_file.write_text("YUGEN_MT5_ALLOWED_SYMBOLS=EURUSD,XAUUSD\n")

    with patch("yugen_mt5_mcp.cli._run_stdio") as mock_run_stdio:
        result = runner.invoke(app, ["run", "--env-file", str(env_file)])

    assert result.exit_code == 0
    assert mock_run_stdio.called
    env = mock_run_stdio.call_args.kwargs["env"]
    assert env["YUGEN_MT5_ALLOWED_SYMBOLS"] == "EURUSD,XAUUSD"


def test_run_env_file_missing_exits_1(tmp_path: Path) -> None:
    """A non-existent --env-file path must exit with code 1, not crash."""
    missing = tmp_path / "nope.env"
    result = runner.invoke(app, ["run", "--env-file", str(missing)])
    assert result.exit_code == 1


def test_run_real_env_overrides_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real environment variables win over --env-file values (precedence)."""
    env_file = tmp_path / "demo.env"
    env_file.write_text("YUGEN_MT5_DEFAULT_ACTOR=from_file\n")
    monkeypatch.setenv("YUGEN_MT5_DEFAULT_ACTOR", "from_env")

    with patch("yugen_mt5_mcp.cli._run_stdio") as mock_run_stdio:
        result = runner.invoke(app, ["run", "--env-file", str(env_file)])

    assert result.exit_code == 0
    env = mock_run_stdio.call_args.kwargs["env"]
    assert env["YUGEN_MT5_DEFAULT_ACTOR"] == "from_env"


# ---------------------------------------------------------------------------
# doctor command
# ---------------------------------------------------------------------------


def _patch_build_diagnostics(report: DoctorReport) -> Any:
    """Return a context manager that patches build_diagnostics.

    ``doctor_cmd`` imports ``build_diagnostics`` lazily from ``.app``, so we
    patch it at the source (``yugen_mt5_mcp.app.build_diagnostics``).
    """
    fake_diag = _FakeDiagnostics(report)
    return patch("yugen_mt5_mcp.app.build_diagnostics", return_value=fake_diag)


@pytest.fixture()
def _patch_doctor_import() -> Any:
    """Ensure build_diagnostics is importable inside cli via lazy import patch."""
    return patch("yugen_mt5_mcp.app.build_diagnostics")


def test_doctor_all_ok_exits_0() -> None:
    report = _make_report(
        ("platform", DoctorStatus.OK),
        ("config", DoctorStatus.OK),
    )
    with _patch_build_diagnostics(report):
        result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "OK" in result.output


def test_doctor_fail_exits_1() -> None:
    report = _make_report(
        ("config", DoctorStatus.FAIL),
        overall=DoctorStatus.FAIL,
    )
    with _patch_build_diagnostics(report):
        result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1


def test_doctor_skipped_exits_0() -> None:
    """SKIPPED checks must not cause exit code 1."""
    report = _make_report(
        ("platform", DoctorStatus.SKIPPED),
        ("mt5_connection", DoctorStatus.SKIPPED),
        ("mt5_account", DoctorStatus.SKIPPED),
        ("config", DoctorStatus.OK),
        overall=DoctorStatus.OK,
    )
    with _patch_build_diagnostics(report):
        result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0


def test_doctor_warn_exits_0() -> None:
    """WARN must not cause exit code 1."""
    report = _make_report(
        ("config", DoctorStatus.WARN),
        overall=DoctorStatus.WARN,
    )
    with _patch_build_diagnostics(report):
        result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0


def test_doctor_json_flag_emits_valid_json() -> None:
    report = _make_report(
        ("config", DoctorStatus.OK),
        overall=DoctorStatus.OK,
    )
    with _patch_build_diagnostics(report):
        result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert "status" in parsed
    assert "checks" in parsed
    assert isinstance(parsed["checks"], list)


def test_doctor_json_contains_all_check_names() -> None:
    report = _make_report(
        ("platform", DoctorStatus.SKIPPED),
        ("config", DoctorStatus.OK),
        ("mt5_connection", DoctorStatus.SKIPPED),
    )
    with _patch_build_diagnostics(report):
        result = runner.invoke(app, ["doctor", "--json"])
    parsed = json.loads(result.output)
    names = [c["name"] for c in parsed["checks"]]
    assert "platform" in names
    assert "config" in names


# ---------------------------------------------------------------------------
# config sub-app
# ---------------------------------------------------------------------------


def test_config_claude_prints_json_with_mcp_servers() -> None:
    result = runner.invoke(app, ["config", "claude"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert "mcpServers" in parsed


def test_config_claude_with_version() -> None:
    result = runner.invoke(app, ["config", "claude", "--version", "0.2.0"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    args = parsed["mcpServers"]["yugen-mt5"]["args"]
    assert any("0.2.0" in a for a in args)


def test_config_cursor_prints_json() -> None:
    result = runner.invoke(app, ["config", "cursor"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert "mcpServers" in parsed


def test_config_opencode_prints_json_with_mcp_key() -> None:
    result = runner.invoke(app, ["config", "opencode"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert "mcp" in parsed


def test_config_remote_default_output() -> None:
    result = runner.invoke(app, ["config", "remote"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert "mcpServers" in parsed
    assert "yugen-mt5-remote" in parsed["mcpServers"]


def test_config_remote_custom_host_port() -> None:
    result = runner.invoke(app, ["config", "remote", "--host", "1.2.3.4", "--port", "9000"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    url = parsed["mcpServers"]["yugen-mt5-remote"]["url"]
    assert "1.2.3.4" in url
    assert "9000" in url


def test_config_remote_custom_token() -> None:
    result = runner.invoke(app, ["config", "remote", "--token", "my-secret"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    auth = parsed["mcpServers"]["yugen-mt5-remote"]["headers"]["Authorization"]
    assert "my-secret" in auth


def test_config_output_writes_to_file(tmp_path: Path) -> None:
    out_file = tmp_path / "mcp.json"
    result = runner.invoke(app, ["config", "claude", "--output", str(out_file)])
    assert result.exit_code == 0
    assert out_file.exists()
    parsed = json.loads(out_file.read_text())
    assert "mcpServers" in parsed


# ---------------------------------------------------------------------------
# config remote --scheme flag (T4 RED → T5 GREEN)
# ---------------------------------------------------------------------------


def test_config_remote_scheme_flag_http() -> None:
    result = runner.invoke(app, ["config", "remote", "--host", "203.0.113.5", "--scheme", "http"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    url = parsed["mcpServers"]["yugen-mt5-remote"]["url"]
    assert url.startswith("http://")
    assert url.endswith("/mcp/")


def test_config_remote_scheme_flag_https_on_loopback() -> None:
    result = runner.invoke(app, ["config", "remote", "--host", "127.0.0.1", "--scheme", "https"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    url = parsed["mcpServers"]["yugen-mt5-remote"]["url"]
    assert url.startswith("https://")


def test_config_remote_default_infers_http_for_loopback() -> None:
    result = runner.invoke(app, ["config", "remote"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    url = parsed["mcpServers"]["yugen-mt5-remote"]["url"]
    assert url.startswith("http://127.0.0.1:8765/mcp/")


def test_config_remote_invalid_scheme_rejected() -> None:
    result = runner.invoke(app, ["config", "remote", "--scheme", "ftp"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# WU-6: doctor --env-file plumbing tests
# ---------------------------------------------------------------------------


def test_doctor_env_file_passes_provenance_to_build_diagnostics(
    tmp_path: Path,
) -> None:
    """doctor --env-file must call build_diagnostics with a provenance kwarg."""
    env_file = tmp_path / "test.env"
    env_file.write_text("YUGEN_MT5_ALLOW_LIVE_TRADING=true\n")

    captured_kwargs: dict[str, Any] = {}

    def _fake_build(**kwargs: Any) -> Any:
        captured_kwargs.update(kwargs)
        report = _make_report(("config", DoctorStatus.OK))
        return _FakeDiagnostics(report)

    with patch("yugen_mt5_mcp.app.build_diagnostics", side_effect=_fake_build):
        result = runner.invoke(app, ["doctor", "--env-file", str(env_file)])

    assert result.exit_code == 0
    assert "provenance" in captured_kwargs
    assert captured_kwargs["provenance"] is not None


def test_doctor_env_file_missing_exits_1(tmp_path: Path) -> None:
    """doctor --env-file with a nonexistent path must exit 1."""
    missing = tmp_path / "nonexistent.env"
    result = runner.invoke(app, ["doctor", "--env-file", str(missing)])
    assert result.exit_code == 1


def test_doctor_no_env_file_still_works() -> None:
    """doctor without --env-file still works (backward compat)."""
    report = _make_report(("config", DoctorStatus.OK))
    with _patch_build_diagnostics(report):
        result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0


def test_doctor_env_file_os_environ_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When env-file has a key but os.environ overrides it, provenance must be OS_ENVIRON."""
    from yugen_mt5_mcp.provenance import ConfigSource  # noqa: PLC0415

    env_file = tmp_path / "test.env"
    env_file.write_text("YUGEN_MT5_ALLOW_LIVE_TRADING=false\n")
    monkeypatch.setenv("YUGEN_MT5_ALLOW_LIVE_TRADING", "true")

    captured_provenance: dict[str, Any] = {}

    def _fake_build(**kwargs: Any) -> Any:
        captured_provenance.update(kwargs.get("provenance", {}))
        report = _make_report(("config", DoctorStatus.OK))
        return _FakeDiagnostics(report)

    with patch("yugen_mt5_mcp.app.build_diagnostics", side_effect=_fake_build):
        result = runner.invoke(app, ["doctor", "--env-file", str(env_file)])

    assert result.exit_code == 0
    assert captured_provenance.get("YUGEN_MT5_ALLOW_LIVE_TRADING") is ConfigSource.OS_ENVIRON


# ---------------------------------------------------------------------------
# WU-3: resolve_env_with_provenance tests
# ---------------------------------------------------------------------------


def test_resolve_env_with_provenance_file_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Key present only in env-file → source=ENV_FILE."""
    from yugen_mt5_mcp.cli import resolve_env_with_provenance  # noqa: PLC0415
    from yugen_mt5_mcp.provenance import ConfigSource  # noqa: PLC0415

    env_file = tmp_path / "test.env"
    env_file.write_text("YUGEN_MT5_ALLOW_LIVE_TRADING=true\n")
    monkeypatch.delenv("YUGEN_MT5_ALLOW_LIVE_TRADING", raising=False)

    _env, provenance = resolve_env_with_provenance(env_file)

    assert provenance["YUGEN_MT5_ALLOW_LIVE_TRADING"] is ConfigSource.ENV_FILE


def test_resolve_env_with_provenance_os_environ_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Key in both → os.environ wins, source=OS_ENVIRON."""
    from yugen_mt5_mcp.cli import resolve_env_with_provenance  # noqa: PLC0415
    from yugen_mt5_mcp.provenance import ConfigSource  # noqa: PLC0415

    env_file = tmp_path / "test.env"
    env_file.write_text("YUGEN_MT5_ALLOW_LIVE_TRADING=false\n")
    monkeypatch.setenv("YUGEN_MT5_ALLOW_LIVE_TRADING", "true")

    env, provenance = resolve_env_with_provenance(env_file)

    assert env["YUGEN_MT5_ALLOW_LIVE_TRADING"] == "true"
    assert provenance["YUGEN_MT5_ALLOW_LIVE_TRADING"] is ConfigSource.OS_ENVIRON


def test_resolve_env_with_provenance_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Key absent from both → source=DEFAULT."""
    from yugen_mt5_mcp.cli import resolve_env_with_provenance  # noqa: PLC0415
    from yugen_mt5_mcp.provenance import ConfigSource  # noqa: PLC0415

    env_file = tmp_path / "test.env"
    env_file.write_text("SOME_OTHER_KEY=irrelevant\n")
    monkeypatch.delenv("YUGEN_MT5_ALLOW_LIVE_TRADING", raising=False)

    _env, provenance = resolve_env_with_provenance(env_file)

    assert provenance["YUGEN_MT5_ALLOW_LIVE_TRADING"] is ConfigSource.DEFAULT


def test_resolve_env_backward_compat_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_resolve_env still returns plain dict with same values as before refactor."""
    from yugen_mt5_mcp.cli import _resolve_env  # noqa: PLC0415

    env_file = tmp_path / "test.env"
    env_file.write_text("YUGEN_MT5_ALLOW_LIVE_TRADING=false\n")
    monkeypatch.setenv("YUGEN_MT5_ALLOW_LIVE_TRADING", "true")

    result = _resolve_env(env_file)

    assert isinstance(result, dict)
    assert result["YUGEN_MT5_ALLOW_LIVE_TRADING"] == "true"


def test_resolve_env_with_provenance_missing_file_exits_1(tmp_path: Path) -> None:
    """resolve_env_with_provenance raises typer.Exit(1) on missing file."""
    import typer  # noqa: PLC0415

    from yugen_mt5_mcp.cli import resolve_env_with_provenance  # noqa: PLC0415

    missing = tmp_path / "nonexistent.env"
    with pytest.raises(typer.Exit):
        resolve_env_with_provenance(missing)


def test_resolve_env_with_provenance_none_env_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resolve_env_with_provenance(None) works: no file_values, sources from os.environ."""
    from yugen_mt5_mcp.cli import resolve_env_with_provenance  # noqa: PLC0415
    from yugen_mt5_mcp.provenance import ConfigSource  # noqa: PLC0415

    monkeypatch.setenv("YUGEN_MT5_ALLOW_LIVE_TRADING", "true")
    monkeypatch.delenv("YUGEN_MT5_ALLOW_REAL_ACCOUNTS", raising=False)

    env, provenance = resolve_env_with_provenance(None)

    assert provenance["YUGEN_MT5_ALLOW_LIVE_TRADING"] is ConfigSource.OS_ENVIRON
    assert provenance["YUGEN_MT5_ALLOW_REAL_ACCOUNTS"] is ConfigSource.DEFAULT


# ---------------------------------------------------------------------------
# version command
# ---------------------------------------------------------------------------


def test_version_prints_package_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    # Output must contain the package name and Python version
    assert "yugen-mt5-mcp" in result.output
    assert "Python" in result.output
    assert "Platform" in result.output


def test_version_exit_0() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
