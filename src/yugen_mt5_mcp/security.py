"""Remote transport security and demo smoke guardrails."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from secrets import compare_digest
from typing import TYPE_CHECKING

from .audit import AuditEvent, AuditStore
from .mt5_adapter import AccountSnapshot, AccountTradeMode

if TYPE_CHECKING:
    from .config import RemoteTransportConfig


DEMO_SMOKE_OPT_IN_ENV = "YUGEN_MT5_ENABLE_DEMO_SMOKE"
DEMO_SMOKE_ACK_ENV = "YUGEN_MT5_DEMO_SMOKE_ACK"
DEMO_SMOKE_SYMBOLS_ENV = "YUGEN_MT5_DEMO_SMOKE_SYMBOLS"
DEMO_SMOKE_MAX_VOLUME_ENV = "YUGEN_MT5_DEMO_SMOKE_MAX_VOLUME"
DEMO_SMOKE_ACK_VALUE = "demo-only"
DEFAULT_DEMO_SMOKE_MAX_VOLUME = Decimal("0.01")
DEFAULT_DEMO_SMOKE_SYMBOLS = ("EURUSD",)


class RemoteSecurityError(PermissionError):
    """Raised when remote access or smoke execution is unsafe."""


@dataclass(slots=True, frozen=True)
class RemoteRequestIdentity:
    actor: str
    client_ip: str


@dataclass(slots=True, frozen=True)
class DemoSmokeControls:
    enabled: bool = False
    acknowledgement: str | None = None
    allowed_symbols: tuple[str, ...] = DEFAULT_DEMO_SMOKE_SYMBOLS
    max_volume: Decimal = DEFAULT_DEMO_SMOKE_MAX_VOLUME

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> DemoSmokeControls:
        enabled = env.get(DEMO_SMOKE_OPT_IN_ENV) == "1"
        if not enabled:
            return cls()

        acknowledgement = env.get(DEMO_SMOKE_ACK_ENV)
        if acknowledgement != DEMO_SMOKE_ACK_VALUE:
            raise RemoteSecurityError(
                "demo smoke opt-in requires demo-only acknowledgement"
            )

        raw_symbols = env.get(DEMO_SMOKE_SYMBOLS_ENV, ",".join(DEFAULT_DEMO_SMOKE_SYMBOLS))
        allowed_symbols = tuple(
            symbol.strip().upper() for symbol in raw_symbols.split(",") if symbol.strip()
        )
        if not allowed_symbols:
            raise RemoteSecurityError("demo smoke requires at least one allowed symbol")

        try:
            max_volume = Decimal(env.get(DEMO_SMOKE_MAX_VOLUME_ENV, "0.01"))
        except InvalidOperation as error:
            raise RemoteSecurityError("demo smoke max volume must be a decimal lot size") from error

        if max_volume <= 0 or max_volume > DEFAULT_DEMO_SMOKE_MAX_VOLUME:
            raise RemoteSecurityError("demo smoke max volume must be > 0 and <= 0.01 lots")

        return cls(
            enabled=True,
            acknowledgement=acknowledgement,
            allowed_symbols=allowed_symbols,
            max_volume=max_volume,
        )

    def validate_account(self, account: AccountSnapshot) -> None:
        if account.trade_mode is AccountTradeMode.REAL:
            raise RemoteSecurityError("demo smoke cannot run against real accounts")

    def validate_request(self, *, symbol: str, volume: Decimal) -> str:
        normalized = symbol.strip().upper()
        if normalized not in self.allowed_symbols:
            raise RemoteSecurityError(
                f"symbol is not in the demo smoke allowlist: {normalized}"
            )
        if volume <= 0 or volume > self.max_volume:
            raise RemoteSecurityError("demo smoke volume exceeds the configured max volume")
        return normalized


class RemoteSecurityManager:
    def __init__(
        self,
        remote_config: RemoteTransportConfig,
        *,
        audit_store: AuditStore,
        actor: str = "mcp.remote",
    ) -> None:
        validate_remote_transport_config(remote_config)
        self._remote_config = remote_config
        self._audit_store = audit_store
        self._actor = actor

    def authorize(
        self,
        *,
        request_id: str,
        client_ip: str,
        authorization_header: str | None,
    ) -> RemoteRequestIdentity:
        try:
            if not _ip_in_allowlist(client_ip, self._remote_config.allowlist):
                raise RemoteSecurityError("client IP is not in the allowlist")

            token = _extract_bearer_token(authorization_header)
            if token is None:
                raise RemoteSecurityError("missing bearer token")
            if not compare_digest(token, self._remote_config.bearer_token or ""):
                raise RemoteSecurityError("invalid bearer token")
        except RemoteSecurityError as error:
            self._audit(
                request_id=request_id,
                decision="blocked",
                client_ip=client_ip,
                authorization_header=authorization_header,
                error=str(error),
            )
            raise

        self._audit(
            request_id=request_id,
            decision="allowed",
            client_ip=client_ip,
            authorization_header=authorization_header,
        )
        return RemoteRequestIdentity(actor=self._actor, client_ip=client_ip)

    def _audit(
        self,
        *,
        request_id: str,
        decision: str,
        client_ip: str,
        authorization_header: str | None,
        error: str | None = None,
    ) -> None:
        context: dict[str, object] = {
            "client_ip": client_ip,
            "authorization": authorization_header,
            "bind_host": self._remote_config.host,
            "bind_port": self._remote_config.port,
            "reverse_proxy": self._remote_config.reverse_proxy,
        }
        if error is not None:
            context["error"] = error
        self._audit_store.append(
            AuditEvent(
                event_type="remote.authorize",
                actor=self._actor,
                request_id=request_id,
                decision=decision,
                context=context,
            )
        )


def validate_remote_transport_config(remote_config: RemoteTransportConfig) -> None:
    if not remote_config.enabled:
        return

    if not remote_config.bearer_token or not remote_config.bearer_token.strip():
        raise RemoteSecurityError("remote transport requires a bearer token")

    if not remote_config.tls_terminated:
        raise RemoteSecurityError("remote transport requires TLS termination")

    if not 1 <= remote_config.port <= 65535:
        raise RemoteSecurityError("remote transport port must be between 1 and 65535")

    if (remote_config.reverse_proxy or "").strip().lower() != "caddy":
        raise RemoteSecurityError(
            "remote transport requires a Caddy reverse proxy for TLS termination"
        )

    bind_ip = _parse_ip_address(remote_config.host, field_name="remote transport host")
    if bind_ip.is_unspecified:
        raise RemoteSecurityError("remote transport host must not use a wildcard bind")
    if not _is_safe_bind_address(bind_ip):
        raise RemoteSecurityError("remote transport host must use a private or loopback bind")

    if not remote_config.allowlist:
        raise RemoteSecurityError("remote transport requires a non-empty allowlist")

    for entry in remote_config.allowlist:
        network = _parse_network(entry)
        if network.prefixlen == 0:
            raise RemoteSecurityError("remote transport allowlist must not allow all addresses")


def _extract_bearer_token(authorization_header: str | None) -> str | None:
    if authorization_header is None:
        return None
    scheme, separator, token = authorization_header.partition(" ")
    if separator == "" or scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _ip_in_allowlist(client_ip: str, allowlist: Sequence[str]) -> bool:
    client_address = _parse_ip_address(client_ip, field_name="client IP")
    return any(client_address in _parse_network(entry) for entry in allowlist)


def _parse_ip_address(
    value: str, *, field_name: str
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    try:
        return ipaddress.ip_address(value)
    except ValueError as error:
        raise RemoteSecurityError(f"{field_name} must be a literal IP address") from error


def _parse_network(value: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    try:
        return ipaddress.ip_network(value, strict=False)
    except ValueError as error:
        raise RemoteSecurityError(f"invalid allowlist entry: {value}") from error


def _is_safe_bind_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return address.is_loopback or address.is_private
