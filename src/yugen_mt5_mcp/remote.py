"""ASGI auth boundary: BearerIPAuthMiddleware + client IP resolution helpers."""

from __future__ import annotations

import ipaddress
from uuid import uuid4

from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .security import RemoteSecurityError, RemoteSecurityManager, is_trusted_local_bind


def trust_proxy_headers_for_bind(host: str) -> bool:
    """Return True when the bind host is loopback or RFC 1918/4193 LAN.

    Only when the socket peer is from a trusted address range is it safe to
    trust X-Forwarded-For — because the terminator (which sets XFF) must itself
    be on that LAN.  Public or unspecified (0.0.0.0) binds are excluded.

    Delegates to ``security.is_trusted_local_bind`` so the XFF-trust decision
    here and the validator's trust-tier decision share ONE definition and can
    never diverge.
    """
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return is_trusted_local_bind(address)


def resolve_client_ip(request: Request, *, trust_proxy_headers: bool) -> str:
    """Resolve the effective client IP for the given request.

    When *trust_proxy_headers* is True and an ``X-Forwarded-For`` header is
    present, the leftmost (original client) entry is returned.  Otherwise the
    raw socket peer address is used.  Returns an empty string when no peer can
    be determined (fails allowlist, keeping the fail-closed contract).
    """
    socket_peer: str | None = request.client.host if request.client else None

    if trust_proxy_headers:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # Leftmost entry is the original client; comma-separated, strip whitespace.
            first_hop = xff.split(",")[0].strip()
            if first_hop:
                return first_hop

    return socket_peer if socket_peer is not None else ""


class BearerIPAuthMiddleware:
    """Pure Starlette ASGI middleware that enforces bearer-token + IP allowlist auth.

    Only HTTP requests are intercepted; websocket and lifespan scopes pass
    straight through to the inner app.  The raw bearer token is never logged
    — the audit layer in :meth:`RemoteSecurityManager.authorize` redacts it.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        security_manager: RemoteSecurityManager,
        trust_proxy_headers: bool,
    ) -> None:
        self.app = app
        self._security_manager = security_manager
        self._trust_proxy_headers = trust_proxy_headers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Pass websocket / lifespan straight through.
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        client_ip = resolve_client_ip(request, trust_proxy_headers=self._trust_proxy_headers)
        authorization_header = request.headers.get("authorization")
        request_id = uuid4().hex

        try:
            self._security_manager.authorize(
                request_id=request_id,
                client_ip=client_ip,
                authorization_header=authorization_header,
            )
        except RemoteSecurityError as error:
            status_code = _reason_to_status(error.reason)
            response = PlainTextResponse(str(error), status_code=status_code)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def _reason_to_status(reason: str) -> int:
    """Map a RemoteSecurityError.reason to an HTTP status code.

    - missing_token / invalid_token → 401 Unauthorized
    - ip_blocked                   → 403 Forbidden
    - config_error                 → 403 Forbidden (safe default)
    """
    if reason in ("missing_token", "invalid_token"):
        return 401
    return 403
