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
from .risk import RiskPolicy
from .server import READ_ONLY_TOOL_NAMES, create_server
from .session import SessionRiskStore
from .trading import BulkTradeService, TradingService

ALLOWED_SYMBOLS_ENV = "YUGEN_MT5_ALLOWED_SYMBOLS"
AUDIT_PATH_ENV = "YUGEN_MT5_AUDIT_PATH"
CONSENT_ENV = "YUGEN_MT5_REAL_ACCOUNT_CONSENT"
ALLOW_LIVE_TRADING_ENV = "YUGEN_MT5_ALLOW_LIVE_TRADING"
ALLOW_REAL_ACCOUNTS_ENV = "YUGEN_MT5_ALLOW_REAL_ACCOUNTS"
DEFAULT_AUDIT_PATH = Path("var/audit.sqlite3")

_TRUTHY = frozenset({"1", "true", "yes", "on"})


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
                message="YUGEN_MT5_ALLOWED_SYMBOLS=* allows every symbol for reads and trading",
            ),
        )

    symbols = tuple(symbol.strip() for symbol in raw_value.split(",") if symbol.strip())
    return symbols, ()


def resolve_audit_path(env: Mapping[str, str]) -> Path:
    raw_value = env.get(AUDIT_PATH_ENV, "").strip()
    if not raw_value:
        return DEFAULT_AUDIT_PATH
    return Path(raw_value)


def _parse_consent_env(env: Mapping[str, str]) -> bool:
    """Return True when YUGEN_MT5_REAL_ACCOUNT_CONSENT is set to a truthy value."""
    return env.get(CONSENT_ENV, "").strip().lower() in _TRUTHY


def _parse_true_false_env(env: Mapping[str, str], key: str) -> bool:
    """Return True only when an environment flag is explicitly set to true."""
    return env.get(key, "").strip().lower() == "true"


def build_runtime(
    *,
    env: Mapping[str, str] | None = None,
    audit_path: Path | None = None,
    adapter_factory: Callable[[], MT5Adapter] = MT5Adapter,
    server_factory: Callable[..., RunnableServer] | None = None,
) -> RuntimeApp:
    runtime_env = os.environ if env is None else env
    resolved_audit_path = resolve_audit_path(runtime_env) if audit_path is None else audit_path
    allowed_symbols, warnings = parse_allowed_symbols(runtime_env)
    real_account_consent_env = _parse_consent_env(runtime_env)
    allow_live_trading = _parse_true_false_env(runtime_env, ALLOW_LIVE_TRADING_ENV)
    allow_real_accounts = _parse_true_false_env(runtime_env, ALLOW_REAL_ACCOUNTS_ENV)
    config = AppConfig(
        audit=AuditConfig(database_path=resolved_audit_path),
        risk=RiskConfig(
            allowed_symbols=allowed_symbols,
            allow_live_trading=allow_live_trading,
            allow_real_accounts=allow_real_accounts,
            real_account_consent_env=real_account_consent_env,
        ),
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
    # Compose trading deps — wired unconditionally; execution-level risk gates
    # (allow_live_trading, real-account ack) control what actually executes.
    session_store = SessionRiskStore()
    risk_policy = RiskPolicy(config=config, session_store=session_store, audit_store=audit_store)
    trading_service = TradingService(
        adapter=adapter,
        risk_policy=risk_policy,
        audit_store=audit_store,
        actor=config.risk.default_actor,
    )
    bulk_service = BulkTradeService(
        trading_service=trading_service,
        adapter=adapter,
        audit_store=audit_store,
    )
    if server_factory is None:
        server = _create_default_server(
            market_data,
            doctor_service,
            trading_service=trading_service,
            bulk_service=bulk_service,
            session_store=session_store,
            config=config,
        )
    else:
        # Injected factories keep the existing (market_data, doctor_service) signature
        # for backward-compatibility.
        server = server_factory(market_data, doctor_service)
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
    *,
    trading_service: TradingService | None = None,
    bulk_service: BulkTradeService | None = None,
    session_store: SessionRiskStore | None = None,
    config: AppConfig | None = None,
) -> RunnableServer:
    return create_server(
        market_data,
        doctor_service=doctor_service,
        trading_service=trading_service,
        bulk_service=bulk_service,
        session_store=session_store,
        config=config,
    )
