"""Application entrypoint composition for local MCP execution."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, TextIO

from .audit import AuditStore
from .config import AppConfig, AuditConfig, RiskConfig
from .doctor import DoctorService, create_default_doctor
from .market_data import MarketDataService
from .mt5_adapter import MT5Adapter
from .server import READ_ONLY_TOOL_NAMES, create_server

ALLOWED_SYMBOLS_ENV = "YUGEN_MT5_ALLOWED_SYMBOLS"
AUDIT_PATH_ENV = "YUGEN_MT5_AUDIT_PATH"
DEFAULT_AUDIT_PATH = Path("var/audit.sqlite3")


class RunnableServer(Protocol):
    def run(
        self,
        transport: Literal["stdio", "http", "sse", "streamable-http"] | None = None,
        show_banner: bool | None = None,
        **transport_kwargs: Any,
    ) -> None: ...


@dataclass(slots=True, frozen=True)
class EntrypointWarning:
    code: str
    message: str


@dataclass(slots=True, frozen=True)
class RuntimeApp:
    server: RunnableServer
    warnings: tuple[EntrypointWarning, ...]


def parse_allowed_symbols(
    env: Mapping[str, str],
) -> tuple[tuple[str, ...], tuple[EntrypointWarning, ...]]:
    raw_value = env.get(ALLOWED_SYMBOLS_ENV, "").strip()
    if not raw_value:
        return (), ()

    if raw_value == "*":
        return ("*",), (
            EntrypointWarning(
                code="allowed_symbols_wildcard",
                message="YUGEN_MT5_ALLOWED_SYMBOLS=* allows every symbol for read tools",
            ),
        )

    symbols = tuple(symbol.strip() for symbol in raw_value.split(",") if symbol.strip())
    return symbols, ()


def resolve_audit_path(env: Mapping[str, str]) -> Path:
    raw_value = env.get(AUDIT_PATH_ENV, "").strip()
    if not raw_value:
        return DEFAULT_AUDIT_PATH
    return Path(raw_value)


def build_runtime(
    *,
    env: Mapping[str, str] | None = None,
    audit_path: Path | None = None,
    adapter_factory: Callable[[], MT5Adapter] = MT5Adapter,
    server_factory: Callable[[MarketDataService, DoctorService], RunnableServer] | None = None,
) -> RuntimeApp:
    runtime_env = os.environ if env is None else env
    resolved_audit_path = resolve_audit_path(runtime_env) if audit_path is None else audit_path
    allowed_symbols, warnings = parse_allowed_symbols(runtime_env)
    config = AppConfig(
        audit=AuditConfig(database_path=resolved_audit_path),
        risk=RiskConfig(allowed_symbols=allowed_symbols),
    )
    adapter = adapter_factory()
    audit_store = AuditStore(resolved_audit_path)
    market_data = MarketDataService(config=config, adapter=adapter, audit_store=audit_store)
    doctor_service = create_default_doctor(
        config=config,
        audit_store=audit_store,
        adapter=adapter,
        read_tool_names=READ_ONLY_TOOL_NAMES,
        entrypoint_warnings=warnings,
    )
    factory = _create_default_server if server_factory is None else server_factory
    server = factory(market_data, doctor_service)
    return RuntimeApp(server=server, warnings=warnings)


def run_stdio(server: RunnableServer) -> None:
    server.run(transport="stdio", show_banner=True)


def emit_warnings(
    warnings: tuple[EntrypointWarning, ...],
    *,
    stream: TextIO = sys.stderr,
) -> None:
    for warning in warnings:
        print(f"WARNING [{warning.code}]: {warning.message}", file=stream)


def main() -> None:
    runtime = build_runtime()
    emit_warnings(runtime.warnings)
    run_stdio(runtime.server)


def _create_default_server(
    market_data: MarketDataService,
    doctor_service: DoctorService,
) -> RunnableServer:
    return create_server(market_data, doctor_service=doctor_service)
