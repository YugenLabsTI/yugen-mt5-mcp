"""Typer CLI — composition root for yugen-mt5-mcp.

This module is the new ``[project.scripts]`` entrypoint (``cli:main``).  It
provides five subcommands:

- ``run``     — start the MCP server (stdio or remote transport)
- ``doctor``  — run readiness checks without starting the server
- ``config``  — print paste-ready client configuration JSON
- ``init``    — interactive wizard that generates an env-var block
- ``version`` — print package and runtime version information

Heavy dependencies (MetaTrader5, uvicorn, fastmcp) are NEVER imported at
module level.  They are lazy-imported inside the command bodies that need them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from .provenance import ConfigSource

# ---------------------------------------------------------------------------
# Top-level Typer application
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="yugen-mt5-mcp",
    no_args_is_help=False,
    add_completion=False,
    help="Secure MCP server for MetaTrader 5.",
)


# ---------------------------------------------------------------------------
# Default callback — bare invocation → stdio run
# ---------------------------------------------------------------------------


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    """Bare invocation defaults to ``run`` in stdio mode."""
    if ctx.invoked_subcommand is None:
        _run_stdio()


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------


def _run_stdio(env: dict[str, str] | None = None) -> None:
    """Start the MCP server in stdio mode (no-arg default path)."""
    from .app import build_runtime, emit_warnings, run_stdio  # noqa: PLC0415
    from .config import TransportMode  # noqa: PLC0415

    runtime = build_runtime(env=env)
    emit_warnings(runtime.warnings)
    if runtime.config.transport.mode is TransportMode.REMOTE:
        # Transport configured via env — honour it even on bare invocation.
        _start_remote(runtime)
    else:
        run_stdio(runtime.server)


def _start_remote(runtime: object) -> None:
    """Start the MCP server in remote (HTTP) mode.

    ``runtime`` must be a ``RuntimeApp`` instance.  Typed as ``object`` here
    to avoid importing ``RuntimeApp`` at module level.
    """
    from .app import run_remote  # noqa: PLC0415

    run_remote(runtime.server, runtime.config.transport.remote, runtime.audit_store)  # type: ignore[attr-defined]


def resolve_env_with_provenance(
    env_file: Path | None,
) -> tuple[dict[str, str], dict[str, ConfigSource]]:
    """Build the runtime environment mapping AND provenance sidecar.

    Values from *env_file* form the base; the real process environment is
    overlaid on top, so explicit environment variables always win over the
    file.  Uses ``dotenv_values`` (NOT ``load_dotenv``) so nothing mutates the
    global ``os.environ`` as a side effect — loading stays explicit.

    Returns ``(merged_env, provenance_map)`` where *provenance_map* is a
    ``dict[str, ConfigSource]`` tracking the origin of each
    ``SAFETY_CRITICAL_KEYS`` entry.
    """
    import os  # noqa: PLC0415

    from .provenance import SAFETY_CRITICAL_KEYS, derive_provenance  # noqa: PLC0415

    file_values: dict[str, str] = {}
    if env_file is not None:
        if not env_file.is_file():
            typer.echo(f"env file not found: {env_file}", err=True)
            raise typer.Exit(code=1)
        from dotenv import dotenv_values  # noqa: PLC0415

        file_values = {k: v for k, v in dotenv_values(env_file).items() if v is not None}

    merged: dict[str, str] = {**file_values, **os.environ}
    provenance = derive_provenance(file_values, os.environ, SAFETY_CRITICAL_KEYS)
    return merged, provenance


def _resolve_env(env_file: Path | None) -> dict[str, str]:
    """Build the runtime environment mapping from an optional ``--env-file``.

    Thin wrapper around ``resolve_env_with_provenance`` that discards the
    provenance sidecar.  Preserves the existing ``{**file_values, **os.environ}``
    return value byte-for-bit.
    """
    return resolve_env_with_provenance(env_file)[0]


@app.command("run")
def run_cmd(
    transport: str = typer.Option(
        "stdio",
        "--transport",
        "-t",
        help="Transport mode: 'stdio' (default) or 'remote'.",
        show_default=True,
    ),
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Bind address for remote transport.",
        show_default=True,
    ),
    port: int = typer.Option(
        8765,
        "--port",
        "-p",
        help="Port for remote transport.",
        show_default=True,
    ),
    env_file: Path | None = typer.Option(
        None,
        "--env-file",
        help="Load environment variables from a file (e.g. ./demo.env). "
        "Real environment variables take precedence over the file.",
        show_default=False,
    ),
) -> None:
    """Start the MCP server.

    Default transport is stdio.  Use ``--transport remote`` to enable the HTTP
    transport (requires the ``[remote]`` extra: ``pip install
    'yugen-mt5-mcp[remote]'``).

    Pass ``--env-file PATH`` to load configuration from a dotenv file instead of
    exporting each variable by hand.  Useful for switching between demo/real
    profiles without retyping the whole environment.
    """
    if transport not in ("stdio", "remote"):
        typer.echo(f"Unknown transport: {transport!r}. Choose 'stdio' or 'remote'.", err=True)
        raise typer.Exit(code=1)

    env = _resolve_env(env_file)

    if transport == "remote":
        try:
            import uvicorn  # noqa: F401, PLC0415
        except ImportError:
            typer.echo(
                "Remote transport requires: pip install 'yugen-mt5-mcp[remote]'",
                err=True,
            )
            raise typer.Exit(code=1) from None

        from .app import build_runtime, emit_warnings  # noqa: PLC0415

        # Allow CLI flags to override env vars for host/port.
        env.setdefault("YUGEN_MT5_REMOTE_ENABLED", "true")
        env["YUGEN_MT5_REMOTE_HOST"] = host
        env["YUGEN_MT5_REMOTE_PORT"] = str(port)

        runtime = build_runtime(env=env)
        emit_warnings(runtime.warnings)
        _start_remote(runtime)
    else:
        _run_stdio(env=env)


# ---------------------------------------------------------------------------
# doctor command
# ---------------------------------------------------------------------------


@app.command("doctor")
def doctor_cmd(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Run readiness checks without starting the MCP server.

    Exits with code 1 if any check reports FAIL.  WARN and SKIPPED checks do
    not affect the exit code.
    """
    from .app import build_diagnostics  # noqa: PLC0415
    from .doctor import DoctorStatus  # noqa: PLC0415

    diagnostics = build_diagnostics()
    report = diagnostics.doctor.run()

    if json_output:
        output = {
            "status": report.status.value,
            "generated_at": report.generated_at.isoformat(),
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "severity": c.severity.value,
                    "summary": c.summary,
                    "remediation": c.remediation,
                }
                for c in report.checks
            ],
        }
        typer.echo(json.dumps(output, indent=2))
    else:
        # Human-readable table
        _STATUS_ICONS = {
            DoctorStatus.OK: "OK     ",
            DoctorStatus.WARN: "WARN   ",
            DoctorStatus.FAIL: "FAIL   ",
            DoctorStatus.SKIPPED: "SKIPPED",
        }
        col_width = max(len(c.name) for c in report.checks) + 2
        generated = report.generated_at.strftime("%Y-%m-%d %H:%M:%S")
        typer.echo(f"\nyugen-mt5-mcp doctor — {generated} UTC\n")
        for check in report.checks:
            icon = _STATUS_ICONS.get(check.status, check.status.value.upper())
            typer.echo(f"  {check.name:<{col_width}} [{icon}]  {check.summary}")
            if check.remediation and check.status is DoctorStatus.FAIL:
                typer.echo(f"  {'':>{col_width}}           -> {check.remediation}")
        typer.echo(f"\nOverall: {report.status.value.upper()}\n")

    has_fail = any(c.status is DoctorStatus.FAIL for c in report.checks)
    if has_fail:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# config sub-app
# ---------------------------------------------------------------------------

config_app = typer.Typer(help="Generate MCP client configuration.")
app.add_typer(config_app, name="config")


def _print_or_save(data: dict[str, object], output: Path | None) -> None:
    """Print *data* as JSON to stdout, or write to *output* when given."""
    dumped = json.dumps(data, indent=2)
    if output is not None:
        output.write_text(dumped, encoding="utf-8")
        typer.echo(f"Config written to {output}", err=True)
    else:
        typer.echo(dumped)


@config_app.command("claude")
def config_claude(
    version: str | None = typer.Option(None, "--version", "-v", help="Pin package version."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write config to file."),
) -> None:
    """Print the Claude Desktop MCP configuration block."""
    from .config_templates import claude_config  # noqa: PLC0415

    _print_or_save(claude_config(version), output)


@config_app.command("cursor")
def config_cursor(
    version: str | None = typer.Option(None, "--version", "-v", help="Pin package version."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write config to file."),
) -> None:
    """Print the Cursor MCP configuration block."""
    from .config_templates import cursor_config  # noqa: PLC0415

    _print_or_save(cursor_config(version), output)


@config_app.command("opencode")
def config_opencode(
    version: str | None = typer.Option(None, "--version", "-v", help="Pin package version."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write config to file."),
) -> None:
    """Print the OpenCode MCP configuration block.

    NOTE: Verify the format against https://opencode.ai/docs/mcp-servers before
    use — the schema was correct as of June 2026.
    """
    from .config_templates import opencode_config  # noqa: PLC0415

    _print_or_save(opencode_config(version), output)


@config_app.command("remote")
def config_remote(
    host: str = typer.Option("127.0.0.1", "--host", help="Remote server host."),
    port: int = typer.Option(8765, "--port", help="Remote server port."),
    token: str = typer.Option("<BEARER_TOKEN>", "--token", help="Bearer token placeholder."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write config to file."),
) -> None:
    """Print a remote HTTP transport configuration block."""
    from .config_templates import remote_config  # noqa: PLC0415

    _print_or_save(remote_config(host=host, port=port, token=token), output)


# ---------------------------------------------------------------------------
# init command — interactive wizard
# ---------------------------------------------------------------------------


@app.command("init")
def init_cmd(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of KEY=VALUE."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write output to file."),
) -> None:
    """Interactive wizard to generate YUGEN_MT5_* environment variables.

    Prompts for server settings and prints an env block you can source or
    paste into a config file.  Does NOT require MetaTrader5 to be connected.
    """
    typer.echo("yugen-mt5-mcp init — configuration wizard\n")

    allowed_symbols: str = typer.prompt(
        "Allowed symbols (comma-separated, or * for all)",
        default="*",
    )
    allow_live_trading: bool = typer.confirm(
        "Allow live trading? (default: No — demo/backtest only)",
        default=False,
    )
    allow_real_accounts: bool = typer.confirm(
        "Allow real (non-demo) accounts?",
        default=False,
    )
    max_order_volume: str = typer.prompt(
        "Max order volume (lot size, or 'unlimited')",
        default="1.0",
    )
    max_symbol_exposure: str = typer.prompt(
        "Max symbol exposure (lot size, or 'unlimited')",
        default="1.0",
    )
    audit_path: str = typer.prompt(
        "Audit database path (leave blank for default: var/audit.sqlite3)",
        default="",
    )

    env_vars: dict[str, str] = {
        "YUGEN_MT5_ALLOWED_SYMBOLS": allowed_symbols,
        "YUGEN_MT5_ALLOW_LIVE_TRADING": "true" if allow_live_trading else "false",
        "YUGEN_MT5_ALLOW_REAL_ACCOUNTS": "true" if allow_real_accounts else "false",
        "YUGEN_MT5_MAX_ORDER_VOLUME": max_order_volume,
        "YUGEN_MT5_MAX_SYMBOL_EXPOSURE": max_symbol_exposure,
    }
    if audit_path.strip():
        env_vars["YUGEN_MT5_AUDIT_PATH"] = audit_path.strip()

    if json_output:
        text = json.dumps(env_vars, indent=2)
    else:
        lines = [f"{k}={v}" for k, v in env_vars.items()]
        text = "\n".join(lines)

    if output is not None:
        output.write_text(text, encoding="utf-8")
        typer.echo(f"\nConfig written to {output}", err=True)
    else:
        typer.echo(f"\n{text}")


# ---------------------------------------------------------------------------
# version command
# ---------------------------------------------------------------------------


@app.command("version")
def version_cmd() -> None:
    """Print package version, Python version, and platform information."""
    import importlib.metadata  # noqa: PLC0415
    import platform  # noqa: PLC0415

    ver = importlib.metadata.version("yugen-mt5-mcp")
    typer.echo(f"yugen-mt5-mcp {ver}")
    typer.echo(f"Python {sys.version}")
    typer.echo(f"Platform {platform.platform()}")

    # MT5 version: only on win32 and only if already connected — never connect here.
    if sys.platform == "win32":
        try:
            import MetaTrader5 as mt5  # noqa: PLC0415, N813

            info = mt5.terminal_info()
            if info is not None:
                typer.echo(f"MetaTrader5 terminal: {info.path} (build {info.build})")
        except Exception:  # noqa: BLE001
            pass  # MT5 unavailable or not connected — silently skip


# ---------------------------------------------------------------------------
# Package entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    """Package entrypoint registered in ``[project.scripts]``."""
    app()
