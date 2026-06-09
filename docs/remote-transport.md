# Remote transport deployment guide

This guide covers deploying yugen-mt5-mcp in `remote` mode, where a client on a
different machine or network boundary connects to the server over HTTP with
bearer-token authentication.

## Quick orientation

```
Client
  -> [TLS terminator: Caddy / nginx / cloud LB / Cloudflare Tunnel]
  -> HTTP on loopback/private  ->  yugen-mt5-mcp (uvicorn)
                                        -> MT5 terminal
```

TLS is the deployment's responsibility. yugen-mt5-mcp is TLS-agnostic — any
proxy or cloud service that terminates HTTPS and forwards plaintext HTTP to the
process works. Caddy is the recommended example because it handles certificate
renewal automatically.

## Environment variables

| Variable | Type | Default | Description |
|---|---|---|---|
| `YUGEN_MT5_REMOTE_ENABLED` | bool (`true`/`false`) | `false` | Switches from stdio to HTTP transport |
| `YUGEN_MT5_REMOTE_HOST` | string | `127.0.0.1` | Bind address for the HTTP listener |
| `YUGEN_MT5_REMOTE_PORT` | int 1–65535 | `8765` | Port for the HTTP listener |
| `YUGEN_MT5_REMOTE_PATH` | string | `/mcp/` | HTTP path served by the remote transport |
| `YUGEN_MT5_REMOTE_BEARER_TOKEN` | string | required when enabled | Secret token — clients must send `Authorization: Bearer <token>` |
| `YUGEN_MT5_REMOTE_TLS_TERMINATED` | bool | `false` | Set to `true` when an upstream proxy handles TLS (declaration only, not enforced per-request) |
| `YUGEN_MT5_REMOTE_ALLOWLIST` | comma-separated CIDRs or `*` | loopback + RFC 1918 | IP allowlist for incoming connections; `*` means allow any IP |
| `YUGEN_MT5_REMOTE_ALLOW_INSECURE` | bool | `false` | Opt-out of the TLS requirement for public binds (risk acknowledged — see below) |
| `YUGEN_MT5_REMOTE_STATELESS_HTTP` | bool | `false` | Use stateless HTTP mode (no server-side session; trades off efficiency for simpler proxying) |

All boolean variables use `true` / `false` (case-insensitive, `true` is the only
truthy value — any other string, including `1` or `yes`, is treated as `false`).

## Trust-tier model

The server derives a **trust tier** from the bind address:

| Tier | Condition | TLS requirement |
|---|---|---|
| **trusted-local** | Bind is loopback (`127.x`, `::1`) or RFC 1918 private (`10.x`, `172.16–31.x`, `192.168.x`) | TLS optional — token alone is sufficient |
| **public** | Any other address, including `0.0.0.0` | TLS required (`YUGEN_MT5_REMOTE_TLS_TERMINATED=true`) unless `YUGEN_MT5_REMOTE_ALLOW_INSECURE=true` |

The default bind is `127.0.0.1` (loopback, trusted-local) so a fresh enable
with just a bearer token is safe without configuring TLS.

### Default allowlist

When `YUGEN_MT5_REMOTE_ALLOWLIST` is not set, the server defaults to accepting
connections from loopback and RFC 1918 private ranges:

```
127.0.0.1/32, ::1/128, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
```

This is a safe default for trusted-local deployments. Tighten it to the
specific CIDR(s) you control in production.

## Recommended deployment: Caddy (public VPS)

Caddy handles HTTPS certificates automatically via ACME and forwards plaintext
HTTP to the loopback listener. This is the recommended path for a public VPS.

### Sample Caddyfile

```caddyfile
# Replace mcp.example.com with your actual domain.
# Caddy obtains and renews a Let's Encrypt certificate automatically.
mcp.example.com {
    reverse_proxy 127.0.0.1:8765
}
```

### Server configuration

```bash
# On the VPS — loopback bind so only Caddy (on the same host) can reach the port.
export YUGEN_MT5_REMOTE_ENABLED=true
export YUGEN_MT5_REMOTE_HOST=127.0.0.1
export YUGEN_MT5_REMOTE_PORT=8765
export YUGEN_MT5_REMOTE_BEARER_TOKEN=<strong-random-secret>
export YUGEN_MT5_REMOTE_TLS_TERMINATED=true
# Allowlist: accept connections from 127.0.0.1 only (Caddy is on the same host).
export YUGEN_MT5_REMOTE_ALLOWLIST=127.0.0.1/32

python -m yugen_mt5_mcp
```

The client connects to `https://mcp.example.com/mcp/` with the bearer token in
the `Authorization` header. Caddy forwards the request over loopback to
yugen-mt5-mcp, which sees the socket peer as `127.0.0.1` and trusts the
`X-Forwarded-For` header Caddy sets. The server enforces the token and the
allowlist before any MCP processing occurs.

## Alternative TLS providers

Any TLS terminator that proxies plaintext HTTP to the bind address works.
Set `YUGEN_MT5_REMOTE_TLS_TERMINATED=true` to declare that TLS is handled
upstream (this satisfies the public-bind security requirement).

The `reverse_proxy` field on the config is informational metadata — it does not
change the server's behavior.

**nginx (with certbot)**

```nginx
server {
    listen 443 ssl;
    server_name mcp.example.com;
    ssl_certificate     /etc/letsencrypt/live/mcp.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mcp.example.com/privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:8765;
        proxy_set_header   X-Forwarded-For $remote_addr;
        proxy_set_header   Host $host;
    }
}
```

**Cloud load balancer / Cloudflare Tunnel**

Point the load balancer or tunnel to `127.0.0.1:8765`. Set
`YUGEN_MT5_REMOTE_TLS_TERMINATED=true`. The cloud edge handles the certificate;
the MCP process never sees raw TLS.

## ALLOW_INSECURE escape hatch

`YUGEN_MT5_REMOTE_ALLOW_INSECURE=true` disables the TLS requirement for public
binds. Use this only in controlled environments where the network path between
client and server is already secured by other means (e.g., a VPN or a private
cloud network with no public ingress).

**Risk**: with `ALLOW_INSECURE` active, the bearer token is transmitted in
cleartext over the network. Anyone who can observe the traffic can capture the
token and impersonate a legitimate client. The doctor's posture check reports
this as CRITICAL to keep the risk visible.

## WSL / Windows interop

WSL's default NAT networking mode means the WSL guest cannot reach the Windows
host via `127.0.0.1` — they are on separate loopback namespaces.

Two options:

### Option A — WSL mirrored networking (recommended)

Enable mirrored networking in `.wslconfig` (Windows 11 22H2+):

```ini
[wsl2]
networkingMode=mirrored
```

With mirrored networking, `127.0.0.1` is shared between Windows and WSL. The
server stays on its loopback default and the client in WSL reaches it directly.
No allowlist change needed.

### Option B — bind to the WSL private LAN IP (NAT mode)

Find the Windows host address from inside WSL:

```bash
cat /etc/resolv.conf | grep nameserver | awk '{print $2}'
# e.g., 172.20.0.1
```

Bind the server to that address:

```bash
export YUGEN_MT5_REMOTE_HOST=172.20.0.1   # the Windows host LAN IP from WSL's perspective
export YUGEN_MT5_REMOTE_ALLOWLIST=172.16.0.0/12   # covers the WSL NAT subnet
export YUGEN_MT5_REMOTE_BEARER_TOKEN=<secret>
# No TLS_TERMINATED needed — 172.20.0.1 is an RFC 1918 private address (trusted-local tier).
```

`172.16.0.0/12` covers the full RFC 1918 B-class range that WSL's NAT assigns.
Tighten to the specific `/32` if you know the address is stable.

## Doctor posture check

Run the built-in doctor to verify the posture before deploying:

```bash
# The doctor check is invoked via the MCP doctor tool.
# It reports trust_tier, tls_terminated, allowlist_entries, and any warnings.
```

The doctor emits:

| Condition | Severity | Message |
|---|---|---|
| Public bind, ALLOW_INSECURE active | CRITICAL | "INSECURE: public bind without TLS — token is transmitted in cleartext" |
| Public bind, TLS, wildcard allowlist (`*`) | WARNING | "allowlist is open (*) — any IP may attempt connection; token is the only gate" |
| Trusted-local bind, wildcard allowlist | INFO | "allowlist is open (*) on trusted-local bind — consider restricting to known CIDRs" |
| All other configurations | (no warning) | Clean posture |

The bearer token value is never emitted in doctor output.

## Security summary

| Layer | Mechanism |
|---|---|
| Transport encryption | TLS terminator (Caddy, nginx, cloud LB, Cloudflare Tunnel) — not in-process |
| Authentication | Bearer token checked with `secrets.compare_digest` on every request |
| Authorization | Client IP checked against CIDR allowlist before token validation |
| XFF trust | Trusted only when socket peer is loopback/private (terminator is co-located) |
| Audit | Every authorized and blocked request is appended to the SQLite audit log with the token redacted |
| Default posture | Loopback bind, loopback+RFC 1918 allowlist, TLS optional for trusted-local |
