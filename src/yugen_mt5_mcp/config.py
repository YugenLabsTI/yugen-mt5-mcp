"""Configuration models and startup validation for the MT5 MCP server."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import time
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when application configuration is unsafe or inconsistent."""


class TransportMode(StrEnum):
    STDIO = "stdio"
    REMOTE = "remote"


def _as_tuple(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, list | tuple):
        raise ConfigError("allowlist must be a list or tuple of CIDR strings")
    return tuple(str(value) for value in values)


def _as_optional_time(value: Any) -> time | None:
    if value is None:
        return None
    if isinstance(value, time):
        return value
    try:
        return time.fromisoformat(str(value))
    except ValueError as error:
        raise ConfigError(f"invalid trading window time: {value}") from error


@dataclass(slots=True, frozen=True)
class RemoteTransportConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    bearer_token: str | None = None
    tls_terminated: bool = False
    allowlist: tuple[str, ...] = ("127.0.0.1/32", "::1/128")

    def validate(self) -> None:
        if not self.enabled:
            return

        if not self.bearer_token or not self.bearer_token.strip():
            raise ConfigError("remote transport requires a bearer token")

        if not self.tls_terminated:
            raise ConfigError("remote transport requires TLS termination")

        if not 1 <= self.port <= 65535:
            raise ConfigError("remote transport port must be between 1 and 65535")

        try:
            bind_ip = ipaddress.ip_address(self.host)
        except ValueError as error:
            raise ConfigError("remote transport host must be a literal IP address") from error

        if bind_ip.is_unspecified:
            raise ConfigError("remote transport host must not use a wildcard bind")

        if not self.allowlist:
            raise ConfigError("remote transport requires a non-empty allowlist")

        for entry in self.allowlist:
            try:
                network = ipaddress.ip_network(entry, strict=False)
            except ValueError as error:
                raise ConfigError(f"invalid allowlist entry: {entry}") from error

            if network.prefixlen == 0:
                raise ConfigError("remote transport allowlist must not allow all addresses")


@dataclass(slots=True, frozen=True)
class TransportConfig:
    mode: TransportMode = TransportMode.STDIO
    remote: RemoteTransportConfig = field(default_factory=RemoteTransportConfig)

    def validate(self) -> None:
        if self.mode is TransportMode.STDIO:
            if self.remote.enabled:
                raise ConfigError("remote transport must stay disabled in stdio mode")
            return

        if not self.remote.enabled:
            raise ConfigError("remote mode requires remote transport to be enabled")
        self.remote.validate()


@dataclass(slots=True, frozen=True)
class RiskConfig:
    allowed_symbols: tuple[str, ...] = ()
    allowed_account_modes: tuple[str, ...] = ()
    max_order_volume: Decimal = Decimal("1.0")
    max_symbol_exposure: Decimal = Decimal("1.0")
    allow_live_trading: bool = False
    allow_real_accounts: bool = False
    trading_window_start: time | None = None
    trading_window_end: time | None = None


@dataclass(slots=True, frozen=True)
class AuditConfig:
    database_path: Path = Path("var/audit.sqlite3")


@dataclass(slots=True, frozen=True)
class AppConfig:
    transport: TransportConfig = field(default_factory=TransportConfig)
    audit: AuditConfig = field(default_factory=AuditConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)

    def validate_startup(self) -> None:
        self.transport.validate()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> AppConfig:
        transport_data = payload.get("transport", {})
        remote_data = transport_data.get("remote", {})
        audit_data = payload.get("audit", {})
        risk_data = payload.get("risk", {})

        remote = RemoteTransportConfig(
            enabled=bool(remote_data.get("enabled", False)),
            host=str(remote_data.get("host", "127.0.0.1")),
            port=int(remote_data.get("port", 8765)),
            bearer_token=remote_data.get("bearer_token"),
            tls_terminated=bool(remote_data.get("tls_terminated", False)),
            allowlist=_as_tuple(remote_data.get("allowlist", ("127.0.0.1/32", "::1/128"))),
        )
        transport = TransportConfig(
            mode=TransportMode(str(transport_data.get("mode", TransportMode.STDIO.value))),
            remote=remote,
        )
        audit = AuditConfig(
            database_path=Path(str(audit_data.get("database_path", "var/audit.sqlite3"))),
        )
        risk = RiskConfig(
            allowed_symbols=_as_tuple(risk_data.get("allowed_symbols", ())),
            allowed_account_modes=_as_tuple(risk_data.get("allowed_account_modes", ())),
            max_order_volume=Decimal(str(risk_data.get("max_order_volume", "1.0"))),
            max_symbol_exposure=Decimal(str(risk_data.get("max_symbol_exposure", "1.0"))),
            allow_live_trading=bool(risk_data.get("allow_live_trading", False)),
            allow_real_accounts=bool(risk_data.get("allow_real_accounts", False)),
            trading_window_start=_as_optional_time(risk_data.get("trading_window_start")),
            trading_window_end=_as_optional_time(risk_data.get("trading_window_end")),
        )

        config = cls(transport=transport, audit=audit, risk=risk)
        config.validate_startup()
        return config
