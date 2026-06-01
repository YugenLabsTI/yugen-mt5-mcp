"""Application entrypoint composition for local MCP execution."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, TextIO

from .audit import AuditStore
from .config import AppConfig, RiskConfig
from .market_data import MarketDataService
from .mt5_adapter import MT5Adapter
from .server import create_server

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
    adapter_factory: Callable[[], object] = MT5Adapter,
    server_factory: Callable[[AppConfig, object, Path], RunnableServer] | None = None,
) -> RuntimeApp:
    runtime_env = os.environ if env is None else env
    resolved_audit_path = resolve_audit_path(runtime_env) if audit_path is None else audit_path
    allowed_symbols, warnings = parse_allowed_symbols(runtime_env)
    config = AppConfig(risk=RiskConfig(allowed_symbols=allowed_symbols))
    adapter = adapter_factory()
    factory = _create_default_server if server_factory is None else server_factory
    server = factory(config, adapter, resolved_audit_path)
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


def _create_default_server(config: AppConfig, adapter: object, audit_path: Path) -> RunnableServer:
    if not isinstance(adapter, MT5Adapter):
        raise TypeError("default server factory requires an MT5Adapter")
    service = MarketDataService(
        config=config,
        adapter=adapter,
        audit_store=AuditStore(audit_path),
    )
    return create_server(service)
