"""Application entrypoint composition for local MCP execution."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal, Protocol, TextIO

from .audit import AuditStore
from .chart_bridge import ChartBridgeConfig
from .config import AppConfig, AuditConfig, ConfigError, RiskConfig
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
MAX_SYMBOL_EXPOSURE_ENV = "YUGEN_MT5_MAX_SYMBOL_EXPOSURE"
MAX_ORDER_VOLUME_ENV = "YUGEN_MT5_MAX_ORDER_VOLUME"
DEFAULT_AUDIT_PATH = Path("var/audit.sqlite3")
DEFAULT_RISK_LIMIT = Decimal("1.0")

# Chart bridge env vars
CHART_SHARED_SECRET_ENV = "YUGEN_MT5_CHART_SHARED_SECRET"
CHART_PIPE_NAME_ENV = "YUGEN_MT5_CHART_PIPE_NAME"
CHART_TIMEOUT_ENV = "YUGEN_MT5_CHART_TIMEOUT_SECONDS"
_DEFAULT_CHART_PIPE_NAME = "yugen_chart_bridge"
_DEFAULT_CHART_TIMEOUT = 1.0

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_UNLIMITED_TOKENS = frozenset({"unlimited"})


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


def parse_risk_limit(
    env: Mapping[str, str],
    key: str,
    *,
    default: Decimal,
) -> tuple[Decimal | None, EntrypointWarning | None]:
    """Parse a numeric risk-limit env var.

    Returns ``(limit, warning)`` where ``limit`` is ``None`` when the gate is
    disabled. Unset/blank falls back to ``default``. ``"unlimited"`` or any
    finite negative number disables the limit and emits a transparency warning.
    A finite positive number is the limit. Anything else — ``0``, ``nan``,
    ``inf``, ``"none"``, or unparsable text — raises ``ConfigError`` so the
    misconfiguration surfaces at startup instead of silently defaulting or
    disabling a safety gate.
    """
    raw_value = env.get(key, "").strip()
    if not raw_value:
        return default, None
    if raw_value.lower() in _UNLIMITED_TOKENS:
        return None, _unlimited_warning(key)
    try:
        value = Decimal(raw_value)
    except InvalidOperation as error:
        raise ConfigError(_limit_error(key, raw_value)) from error
    if not value.is_finite():
        raise ConfigError(_limit_error(key, raw_value))
    if value < 0:
        return None, _unlimited_warning(key)
    if value == 0:
        raise ConfigError(_limit_error(key, raw_value))
    return value, None


def _limit_error(key: str, raw_value: str) -> str:
    return (
        f"{key} must be a positive number, 'unlimited', or a negative number to "
        f"disable the limit; got {raw_value!r}"
    )


def _unlimited_warning(key: str) -> EntrypointWarning:
    return EntrypointWarning(
        code="risk_limit_unlimited",
        message=f"{key}=unlimited removes the configured risk limit",
    )


def parse_chart_bridge_config(
    env: Mapping[str, str],
) -> ChartBridgeConfig | None:
    """Parse chart bridge configuration from the environment.

    Returns ``None`` when ``YUGEN_MT5_CHART_SHARED_SECRET`` is unset or blank —
    the bridge is disabled and no chart tools are registered.

    When the secret is present, parses pipe_name and timeout_seconds (mirroring
    the parse_risk_limit fail-loud pattern), then returns a validated
    ``ChartBridgeConfig``.

    Raises:
        ConfigError: when timeout_seconds is set but non-positive or unparsable.
    """
    raw_secret = env.get(CHART_SHARED_SECRET_ENV, "").strip()
    if not raw_secret:
        return None

    pipe_name = env.get(CHART_PIPE_NAME_ENV, "").strip() or _DEFAULT_CHART_PIPE_NAME

    raw_timeout = env.get(CHART_TIMEOUT_ENV, "").strip()
    if raw_timeout:
        try:
            timeout_seconds = float(raw_timeout)
        except ValueError as error:
            raise ConfigError(
                f"{CHART_TIMEOUT_ENV} (chart bridge timeout) must be a positive number; "
                f"got {raw_timeout!r}"
            ) from error
        if timeout_seconds <= 0:
            raise ConfigError(
                f"{CHART_TIMEOUT_ENV} (chart bridge timeout) must be a positive number; "
                f"got {raw_timeout!r}"
            )
    else:
        timeout_seconds = _DEFAULT_CHART_TIMEOUT

    return ChartBridgeConfig(
        pipe_name=pipe_name,
        shared_secret=raw_secret,
        timeout_seconds=timeout_seconds,
    )


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
    max_symbol_exposure, exposure_warning = parse_risk_limit(
        runtime_env, MAX_SYMBOL_EXPOSURE_ENV, default=DEFAULT_RISK_LIMIT
    )
    max_order_volume, order_volume_warning = parse_risk_limit(
        runtime_env, MAX_ORDER_VOLUME_ENV, default=DEFAULT_RISK_LIMIT
    )
    warnings += tuple(w for w in (exposure_warning, order_volume_warning) if w is not None)

    # Chart bridge — disabled when YUGEN_MT5_CHART_SHARED_SECRET is not set.
    # Disabled is the normal default state for this opt-in feature; no warning is
    # emitted. parse_chart_bridge_config raises ConfigError at startup for invalid
    # timeout when the secret IS set. Slice C2 will consume this config to wire
    # ChartBridgeClient into create_server.
    _chart_bridge_config = parse_chart_bridge_config(runtime_env)

    config = AppConfig(
        audit=AuditConfig(database_path=resolved_audit_path),
        risk=RiskConfig(
            allowed_symbols=allowed_symbols,
            allow_live_trading=allow_live_trading,
            allow_real_accounts=allow_real_accounts,
            real_account_consent_env=real_account_consent_env,
            max_symbol_exposure=max_symbol_exposure,
            max_order_volume=max_order_volume,
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
