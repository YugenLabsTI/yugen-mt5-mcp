"""Loopback chart bridge client and explicit protocol contract."""

from __future__ import annotations

import hmac
import ipaddress
import json
import socket
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from typing import Any, cast
from uuid import uuid4

from .audit import AuditEvent, AuditStore

SCHEMA_VERSION = "2026-05-31"


class ChartBridgeError(RuntimeError):
    """Raised when a chart bridge request fails."""


class ChartBridgeProtocolError(ChartBridgeError):
    """Raised when the bridge returns an invalid or unverified response."""


class ChartBridgeTimeoutError(ChartBridgeError):
    """Raised when the bridge does not answer before the configured timeout."""


class ChartBridgeAction(StrEnum):
    LIST_CHARTS = "list_charts"
    CREATE_OBJECT = "create_object"
    UPDATE_OBJECT = "update_object"
    DELETE_OBJECT = "delete_object"


@dataclass(slots=True, frozen=True)
class ChartBridgeConfig:
    host: str = "127.0.0.1"
    port: int = 18888
    shared_secret: str = ""
    timeout_seconds: float = 1.0

    def validate(self) -> None:
        try:
            address = ipaddress.ip_address(self.host)
        except ValueError as error:
            raise ValueError("chart bridge host must be a literal IP address") from error
        if not address.is_loopback:
            raise ValueError("chart bridge host must be a loopback address")
        if not 1 <= self.port <= 65535:
            raise ValueError("chart bridge port must be between 1 and 65535")
        if not self.shared_secret.strip():
            raise ValueError("chart bridge shared_secret is required")
        if self.timeout_seconds <= 0:
            raise ValueError("chart bridge timeout_seconds must be positive")


@dataclass(slots=True, frozen=True)
class ChartSelector:
    chart_id: int | None = None
    symbol: str | None = None
    timeframe: str | None = None

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.chart_id is not None:
            payload["chart_id"] = self.chart_id
        if self.symbol is not None and self.symbol.strip():
            payload["symbol"] = self.symbol.strip().upper()
        if self.timeframe is not None and self.timeframe.strip():
            payload["timeframe"] = self.timeframe.strip().upper()
        if not payload:
            raise ValueError("chart selector requires chart_id, symbol, or timeframe")
        return payload


@dataclass(slots=True, frozen=True)
class ChartObjectPoint:
    time: str | None = None
    price: float | None = None
    index: int | None = None

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.time is not None:
            payload["time"] = self.time
        if self.price is not None:
            payload["price"] = self.price
        if self.index is not None:
            payload["index"] = self.index
        if not payload:
            raise ValueError("chart object points must contain at least one coordinate field")
        return payload


@dataclass(slots=True, frozen=True)
class ChartObjectSpec:
    name: str
    object_type: str
    properties: Mapping[str, object] = field(default_factory=dict)
    points: tuple[ChartObjectPoint, ...] = ()

    def as_payload(self) -> dict[str, object]:
        normalized_name = self.name.strip()
        normalized_type = self.object_type.strip().upper()
        if not normalized_name:
            raise ValueError("chart object name is required")
        if not normalized_type:
            raise ValueError("chart object type is required")
        return {
            "name": normalized_name,
            "object_type": normalized_type,
            "properties": dict(self.properties),
            "points": [point.as_payload() for point in self.points],
        }


@dataclass(slots=True, frozen=True)
class ChartDescriptor:
    chart_id: int
    symbol: str
    timeframe: str


@dataclass(slots=True, frozen=True)
class ChartBridgeAck:
    request_id: str
    action: str
    status: str
    verified: bool
    error_code: str | None = None
    error_message: str | None = None
    observed_properties: Mapping[str, object] = field(default_factory=dict)


def build_auth_tag(
    *,
    shared_secret: str,
    schema_version: str,
    request_id: str,
    action: str,
    idempotency_key: str,
) -> str:
    message = ":".join((schema_version, request_id, action, idempotency_key)).encode("utf-8")
    digest = hmac.new(shared_secret.encode("utf-8"), message, sha256)
    return digest.hexdigest()


class ChartBridgeClient:
    def __init__(
        self,
        *,
        config: ChartBridgeConfig,
        audit_store: AuditStore,
        actor: str = "mcp.chart_bridge",
    ) -> None:
        config.validate()
        self._config = config
        self._audit_store = audit_store
        self._actor = actor

    def list_charts(self) -> list[ChartDescriptor]:
        request_id = self._request_id()
        payload = self._build_request(
            action=ChartBridgeAction.LIST_CHARTS,
            request_id=request_id,
        )
        try:
            response = self._round_trip(payload)
            charts_payload = response.get("charts")
            if not isinstance(charts_payload, list):
                raise ChartBridgeProtocolError(
                    "chart discovery response must include a charts list"
                )
            charts = [self._parse_chart_descriptor(item) for item in charts_payload]
        except ChartBridgeError as error:
            self._audit("list_charts", request_id, "rejected", {"error": str(error)})
            raise
        self._audit("list_charts", request_id, "acknowledged", {"chart_count": len(charts)})
        return charts

    def create_object(
        self,
        *,
        chart: ChartSelector,
        object_spec: ChartObjectSpec,
        idempotency_key: str | None = None,
    ) -> ChartBridgeAck:
        return self._send_object_command(
            action=ChartBridgeAction.CREATE_OBJECT,
            chart=chart,
            object_spec=object_spec,
            idempotency_key=idempotency_key,
        )

    def update_object(
        self,
        *,
        chart: ChartSelector,
        object_spec: ChartObjectSpec,
        idempotency_key: str | None = None,
    ) -> ChartBridgeAck:
        return self._send_object_command(
            action=ChartBridgeAction.UPDATE_OBJECT,
            chart=chart,
            object_spec=object_spec,
            idempotency_key=idempotency_key,
        )

    def delete_object(
        self,
        *,
        chart: ChartSelector,
        object_name: str,
        idempotency_key: str | None = None,
    ) -> ChartBridgeAck:
        normalized_name = object_name.strip()
        if not normalized_name:
            raise ValueError("chart object name is required")
        return self._send_object_command(
            action=ChartBridgeAction.DELETE_OBJECT,
            chart=chart,
            object_spec=ChartObjectSpec(name=normalized_name, object_type="DELETE"),
            idempotency_key=idempotency_key,
        )

    def _send_object_command(
        self,
        *,
        action: ChartBridgeAction,
        chart: ChartSelector,
        object_spec: ChartObjectSpec,
        idempotency_key: str | None,
    ) -> ChartBridgeAck:
        request_id = self._request_id()
        payload = self._build_request(
            action=action,
            request_id=request_id,
            chart=chart,
            object_spec=object_spec,
            idempotency_key=idempotency_key,
        )
        object_payload = cast(dict[str, object], payload.get("object", {}))
        try:
            response = self._round_trip(payload)
            ack = self._parse_ack(response)
            if ack.status != "ok":
                error_detail = ack.error_code or ack.error_message or ack.status
                raise ChartBridgeProtocolError(
                    f"chart bridge action failed: {error_detail}"
                )
            if not ack.verified:
                raise ChartBridgeProtocolError("chart bridge ACK was not verified")
        except ChartBridgeError as error:
            self._audit(
                action.value,
                request_id,
                "rejected",
                {
                    "chart_selector": payload.get("chart_selector"),
                    "object_name": object_payload.get("name"),
                    "error": str(error),
                },
            )
            raise
        self._audit(
            action.value,
            request_id,
            "acknowledged",
            {
                "chart_selector": payload.get("chart_selector"),
                "object_name": object_payload.get("name"),
                "verified": ack.verified,
                "status": ack.status,
                "observed_properties": dict(ack.observed_properties),
            },
        )
        return ack

    def _build_request(
        self,
        *,
        action: ChartBridgeAction,
        request_id: str,
        chart: ChartSelector | None = None,
        object_spec: ChartObjectSpec | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        normalized_idempotency_key = (idempotency_key or request_id).strip()
        if not normalized_idempotency_key:
            raise ValueError("chart bridge idempotency_key must not be blank")
        payload: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "request_id": request_id,
            "action": action.value,
            "idempotency_key": normalized_idempotency_key,
            "auth_tag": build_auth_tag(
                shared_secret=self._config.shared_secret,
                schema_version=SCHEMA_VERSION,
                request_id=request_id,
                action=action.value,
                idempotency_key=normalized_idempotency_key,
            ),
        }
        if chart is not None:
            payload["chart_selector"] = chart.as_payload()
        if object_spec is not None:
            payload["object"] = object_spec.as_payload()
        return payload

    def _round_trip(self, payload: Mapping[str, object]) -> Mapping[str, Any]:
        raw_request = (json.dumps(dict(payload), sort_keys=True) + "\n").encode("utf-8")
        try:
            with socket.create_connection(
                (self._config.host, self._config.port),
                timeout=self._config.timeout_seconds,
            ) as connection:
                connection.settimeout(self._config.timeout_seconds)
                connection.sendall(raw_request)
                raw_response = self._recv_line(connection)
        except TimeoutError as error:
            raise ChartBridgeTimeoutError("chart bridge request timed out") from error
        except OSError as error:
            raise ChartBridgeError(f"chart bridge connection failed: {error}") from error

        try:
            response = json.loads(raw_response.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise ChartBridgeProtocolError("chart bridge response was not valid JSON") from error
        if not isinstance(response, dict):
            raise ChartBridgeProtocolError("chart bridge response must be a JSON object")
        return cast(Mapping[str, Any], response)

    def _recv_line(self, connection: socket.socket) -> bytes:
        chunks = bytearray()
        while True:
            try:
                chunk = connection.recv(4096)
            except TimeoutError as error:
                raise ChartBridgeTimeoutError("chart bridge request timed out") from error
            if not chunk:
                if chunks:
                    break
                raise ChartBridgeProtocolError("chart bridge closed the connection before replying")
            chunks.extend(chunk)
            if b"\n" in chunk:
                break
        line, *_ = bytes(chunks).split(b"\n", 1)
        return line

    def _parse_chart_descriptor(self, payload: object) -> ChartDescriptor:
        if not isinstance(payload, Mapping):
            raise ChartBridgeProtocolError("chart descriptor must be an object")
        return ChartDescriptor(
            chart_id=int(payload["chart_id"]),
            symbol=str(payload["symbol"]),
            timeframe=str(payload["timeframe"]),
        )

    def _parse_ack(self, payload: Mapping[str, Any]) -> ChartBridgeAck:
        try:
            request_id = str(payload["request_id"])
            action = str(payload["action"])
            status = str(payload["status"])
            verified = bool(payload["verified"])
        except KeyError as error:
            raise ChartBridgeProtocolError(
                f"chart bridge response is missing required field: {error.args[0]}"
            ) from error
        observed_properties = payload.get("observed_properties", {})
        if not isinstance(observed_properties, Mapping):
            raise ChartBridgeProtocolError("observed_properties must be an object when present")
        return ChartBridgeAck(
            request_id=request_id,
            action=action,
            status=status,
            verified=verified,
            error_code=self._optional_string(payload.get("error_code")),
            error_message=self._optional_string(payload.get("error_message")),
            observed_properties=cast(Mapping[str, object], observed_properties),
        )

    def _optional_string(self, value: object) -> str | None:
        if value is None:
            return None
        return str(value)

    def _request_id(self) -> str:
        return f"chart-{uuid4()}"

    def _audit(
        self,
        name: str,
        request_id: str,
        decision: str,
        context: Mapping[str, object],
    ) -> None:
        self._audit_store.append(
            AuditEvent(
                event_type=f"chart_bridge.{name}",
                actor=self._actor,
                request_id=request_id,
                decision=decision,
                context=dict(context),
            )
        )
