# Connection Methods

This guide explains how to connect an AI client (Claude Desktop, Cursor, OpenCode, or Claude Code)
to a running yugen-mt5-mcp server. Choose the method that matches your setup from the table below.

## Overview

| Method | Who it is for | Transport | Connection | Deep-dive |
|--------|--------------|-----------|------------|-----------|
| [1. STDIO via editable install](#method-1--stdio-via-editable-install) | Contributors / developers | stdio | Local only | [install.md](install.md) |
| [2. STDIO via uvx](#method-2--stdio-via-uvx) | Most users (Claude Desktop, Cursor, OpenCode) | stdio | Local only | [install.md](install.md), [cli.md](cli.md) |
| [3. Remote — Windows host + WSL/macOS agent](#method-3--remote-windows-host--wslmacos-agent) | Same-network: WSL agent + Windows MT5 | HTTP | LAN / loopback | [remote-transport.md](remote-transport.md) |
| [4. Remote — VPS + Caddy/TLS](#method-4--remote-vps--caddytls) | Public / cloud deployment | HTTPS | Internet | [remote-transport.md](remote-transport.md) |

---

## Method 1 — STDIO via editable install

> **Contributor / developer path.** This method is intended for people who have cloned the
> repository and want to run the server directly from the source tree. It is not the recommended
> path for general use — see [Method 2](#method-2--stdio-via-uvx) for that.

### Prerequisites

- Python 3.11 or 3.12 on Windows
- MetaTrader 5 terminal open and logged into a demo account
- Repository cloned locally

### Setup

```powershell
git clone https://github.com/YugenLabsTI/yugen-mt5-mcp.git
cd yugen-mt5-mcp
python -m pip install -e ".[dev]"
```

### Start the server

Create a `.env` file with your configuration (see [Reference appendix — Environment variables](#environment-variables)), then:

```powershell
yugen-mt5-mcp run --env-file .env
```

> **AUDIT_PATH gotcha:** desktop clients (Claude Desktop, Cursor, OpenCode) launch the server
> from their own working directory, which makes relative paths like `var/audit.sqlite3` resolve
> to an unexpected location. Use an absolute path for `YUGEN_MT5_AUDIT_PATH` in any `.env` file
> you use with a desktop client. See [AUDIT_PATH warning](#audit_path-warning) in the appendix.

### Client configuration

Use the same client JSON blocks as in [Method 2](#method-2--stdio-via-uvx) but replace the
`command` / `args` with the local script name:

```json
{
  "mcpServers": {
    "yugen-mt5": {
      "command": "yugen-mt5-mcp",
      "args": [],
      "env": {
        "YUGEN_MT5_ALLOWED_SYMBOLS": "EURUSD,XAUUSD",
        "YUGEN_MT5_ALLOW_LIVE_TRADING": "false",
        "YUGEN_MT5_ALLOW_REAL_ACCOUNTS": "false",
        "YUGEN_MT5_AUDIT_PATH": "C:\\absolute\\path\\to\\audit.sqlite3"
      }
    }
  }
}
```

For the full install option matrix, see [docs/install.md](install.md). For development
environment setup and contributing guidelines, see the
[Contributors section in README.md](../README.md#for-contributors).

---

## Method 2 — STDIO via uvx

> **Primary user path.** If you are not a developer working from source, start here.

### Prerequisites

- Windows with MetaTrader 5 installed and logged into a demo account
- [uv](https://docs.astral.sh/uv/getting-started/installation/) installed

### How it works

`uvx` runs the package directly from PyPI in an isolated environment — no separate install step
needed. The package is cached after the first run.

### Client configuration

Pick the block for your client, merge it into the config file shown, and restart the client.

#### Claude Desktop

Config file locations:
- **Windows**: `C:\Users\YOUR_USERNAME\AppData\Roaming\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "yugen-mt5": {
      "command": "uvx",
      "args": ["yugen-mt5-mcp"],
      "env": {
        "YUGEN_MT5_ALLOWED_SYMBOLS": "EURUSD,XAUUSD",
        "YUGEN_MT5_ALLOW_LIVE_TRADING": "false",
        "YUGEN_MT5_ALLOW_REAL_ACCOUNTS": "false",
        "YUGEN_MT5_MAX_ORDER_VOLUME": "1.0",
        "YUGEN_MT5_MAX_SYMBOL_EXPOSURE": "1.0",
        "YUGEN_MT5_AUDIT_PATH": "C:\\Users\\YOUR_USERNAME\\AppData\\Local\\Yugen\\mt5-mcp\\audit.sqlite3"
      }
    }
  }
}
```

Auto-generate this block:

```powershell
yugen-mt5-mcp config claude
```

#### Cursor

Config file: `~/.cursor/mcp.json`

```json
{
  "mcpServers": {
    "yugen-mt5": {
      "command": "uvx",
      "args": ["yugen-mt5-mcp"],
      "env": {
        "YUGEN_MT5_ALLOWED_SYMBOLS": "EURUSD,XAUUSD",
        "YUGEN_MT5_ALLOW_LIVE_TRADING": "false",
        "YUGEN_MT5_ALLOW_REAL_ACCOUNTS": "false",
        "YUGEN_MT5_MAX_ORDER_VOLUME": "1.0",
        "YUGEN_MT5_MAX_SYMBOL_EXPOSURE": "1.0",
        "YUGEN_MT5_AUDIT_PATH": "C:\\Users\\YOUR_USERNAME\\AppData\\Local\\Yugen\\mt5-mcp\\audit.sqlite3"
      }
    }
  }
}
```

Auto-generate:

```powershell
yugen-mt5-mcp config cursor
```

#### OpenCode

Config file: `~/.config/opencode/config.json` (or `opencode.json` at project root)

```json
{
  "mcp": {
    "yugen-mt5": {
      "type": "local",
      "command": ["uvx", "yugen-mt5-mcp"],
      "environment": {
        "YUGEN_MT5_ALLOWED_SYMBOLS": "EURUSD,XAUUSD",
        "YUGEN_MT5_ALLOW_LIVE_TRADING": "false",
        "YUGEN_MT5_ALLOW_REAL_ACCOUNTS": "false",
        "YUGEN_MT5_MAX_ORDER_VOLUME": "1.0",
        "YUGEN_MT5_MAX_SYMBOL_EXPOSURE": "1.0",
        "YUGEN_MT5_AUDIT_PATH": "C:\\Users\\YOUR_USERNAME\\AppData\\Local\\Yugen\\mt5-mcp\\audit.sqlite3"
      },
      "enabled": true
    }
  }
}
```

Auto-generate:

```powershell
yugen-mt5-mcp config opencode
```

> **AUDIT_PATH:** Desktop clients run the server in their own working directory. Always use an
> absolute path for `YUGEN_MT5_AUDIT_PATH`. See [AUDIT_PATH warning](#audit_path-warning).

For the full CLI flag reference, see [docs/cli.md](cli.md).

---

## Method 3 — Remote (Windows host + WSL/macOS agent)

Use this method when MetaTrader 5 runs on a Windows host and your AI agent (Claude Code,
OpenCode, etc.) runs in WSL or on a macOS machine on the same network.

### Architecture

```
  WSL / macOS agent                    Windows host
  ┌────────────────┐                   ┌──────────────────────────┐
  │ Claude Code /  │  HTTP + Bearer    │  yugen-mt5-mcp (remote)  │
  │  OpenCode      │ ────────────────► │  127.0.0.1 or LAN IP     │
  └────────────────┘                   │         │                 │
                                       │         ▼                 │
                                       │   MT5 terminal (IPC)     │
                                       └──────────────────────────┘
```

### Networking: WSL mirrored vs NAT

**WSL mirrored networking (Windows 11 22H2+, recommended):** Enable it in `.wslconfig`,
run `wsl --shutdown`, then restart WSL:

```ini
[wsl2]
networkingMode=mirrored
```

Then keep the server on its default loopback bind and point the WSL agent at
`http://127.0.0.1:8765/mcp/`.

**WSL NAT mode or macOS:** Bind the server to the Windows LAN IP instead. For the NAT subnet,
host-address lookup, and allowlist details, see
[docs/remote-transport.md — WSL / Windows interop](remote-transport.md#wsl--windows-interop).

### Steps

**1. Generate a bearer token** (on the Windows host):

See [Token generation](#token-generation) in the appendix.

**2. Start the server on Windows** (PowerShell):

```powershell
$env:YUGEN_MT5_REMOTE_ENABLED       = "true"
$env:YUGEN_MT5_REMOTE_HOST          = "192.168.1.100"   # your Windows LAN IP; use 127.0.0.1 for WSL mirrored
$env:YUGEN_MT5_REMOTE_PORT          = "8765"
$env:YUGEN_MT5_REMOTE_BEARER_TOKEN  = "<YOUR_TOKEN>"
$env:YUGEN_MT5_ALLOWED_SYMBOLS      = "EURUSD,XAUUSD"

yugen-mt5-mcp run --transport remote
```

For the `[remote]` extra (required for HTTP transport):

```powershell
uv tool install "yugen-mt5-mcp[remote]"
```

**3. Verify server posture** (on Windows):

```powershell
yugen-mt5-mcp doctor
```

See [Doctor verification](#doctor-verification) in the appendix. For an RFC 1918 bind, the
expected output is `remote_transport [OK]` — token alone is sufficient (trusted-local tier,
TLS not required).

**4. Generate the client config** (run anywhere):

```bash
yugen-mt5-mcp config remote --host 192.168.1.100 --port 8765 --token <YOUR_TOKEN>
```

This emits:

```json
{
  "mcpServers": {
    "yugen-mt5-remote": {
      "url": "http://192.168.1.100:8765/mcp/",
      "headers": { "Authorization": "Bearer <YOUR_TOKEN>" }
    }
  }
}
```

The scheme is inferred automatically: RFC 1918 and loopback addresses produce `http://`;
public IP addresses produce `https://`. Use `--scheme http|https` to override.

**5. Verify connectivity** (from the agent machine):

See [curl verification](#curl-verification) in the appendix.

### Deep-dive

For trust-tier model, XFF allowlist mechanics, WSL NAT subnet details, and nginx/Cloudflare
alternatives, see [docs/remote-transport.md](remote-transport.md).

---

## Method 4 — Remote (VPS + Caddy/TLS)

Use this method for a public cloud or internet-facing deployment where the AI agent connects
from anywhere, not just your local network.

### Architecture

Three facts to keep in mind before you start:

1. **The MT5 terminal and the server (`run`) live on the same Windows VPS.** The `MetaTrader5`
   Python package communicates with the terminal over Windows IPC (named pipes). There is no
   way to run the server on a separate machine from the terminal.

2. **Your AI client (Claude Code, OpenCode) runs on your personal machine.** It only needs to
   be an HTTP client that points at the VPS URL with a bearer token. No MT5 installation
   required on the client machine.

3. **The server never does TLS itself.** It always speaks plain HTTP. Caddy, running on the
   same VPS, terminates HTTPS and forwards plain HTTP to `127.0.0.1:8765`.

```
  Your personal machine                      VPS (Windows, AWS EC2)
  ┌──────────────────────┐                  ┌────────────────────────────────────────┐
  │ Claude Code /        │  HTTPS ────────► │ Caddy (TLS) ──HTTP──► yugen-mt5-mcp   │
  │ OpenCode             │                  │               127.0.0.1:8765            │
  └──────────────────────┘                  │                    │                    │
                                            │                    ▼                    │
                                            │           MT5 terminal (IPC)           │
                                            └────────────────────────────────────────┘
```

### Prerequisites

- AWS account (or equivalent) with permission to create EC2 instances
- A **demo** MT5 account (broker login, password, server name). Never use a real account for
  initial setup.
- A domain or subdomain you can point at the VPS via a DNS A record (required for Let's Encrypt
  TLS in Phase B)
- Your AI client (Claude Code, OpenCode) installed on your personal machine

### EC2 setup

**1. Launch an EC2 instance:**

- AMI: *Microsoft Windows Server 2022 Base*
- Instance type: `t3.medium` (minimum — MT5 + Caddy + server together need it)
- Key pair: create a new one (e.g. `yugen-vps.pem`) and save it; you will need it to retrieve
  the Administrator password
- Security Group: create `yugen-mt5-sg` with **RDP (port 3389) restricted to your IP only**.
  Do not open port 8765 yet — that happens in Phase A.
- Storage: 50 GB gp3

**2. Assign an Elastic IP:** EC2 → Elastic IPs → Allocate → Associate to your instance.
This gives you a stable public IP for DNS and the client allowlist. Note it as `ELASTIC_IP`.

**3. Retrieve the Administrator password:** EC2 → select instance → Connect → RDP client →
Get password → upload your `.pem` file → Decrypt. Note the `Administrator` username and password.

**4. Prepare the VPS:** Connect via RDP (`mstsc` or any RDP client) using `ELASTIC_IP` +
Administrator + password. Open **PowerShell as Administrator**:

```powershell
# Install uv (recommended Python manager)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
# Close and reopen PowerShell so the PATH update takes effect.

# Install yugen-mt5-mcp with the remote extra (includes uvicorn)
uv tool install "yugen-mt5-mcp[remote]"

# Verify
yugen-mt5-mcp version
```

For alternative install methods, see [docs/install.md](install.md).

**5. Install and configure MetaTrader 5:** Download the MT5 installer from your broker, install
it on the VPS, open the terminal, and log into your **demo account**. The terminal must remain
open and logged in while the server runs — if it closes, the IPC connection dies. Enable
auto-login on the demo account so it survives restarts.

### Phase A — Plain HTTP test

> **Purpose:** Verify the full connection flow before adding TLS complexity. This phase exposes
> plain HTTP to the internet with the token in cleartext. It is intentional and temporary.
> Tear it down immediately after confirming connectivity.

**1. Get your personal machine's public IP** (run this on your machine, not the VPS):

```bash
curl ifconfig.me
# Example result: 200.123.45.67  →  this is YOUR_PUBLIC_IP
```

If your internet connection uses a dynamic IP, it may change. Update the allowlist and Security
Group rule if that happens.

**2. Open port 8765 in both firewall layers.**

> **Critical gotcha — two firewall layers:** Opening the port in the AWS Security Group lets the
> packet reach the EC2 instance, but **Windows Defender Firewall silently drops it** unless you
> also add an inbound rule for port 8765. Windows blocks non-standard ports by default. The
> symptom is a **connection timeout** (not "connection refused") even when the server is
> listening on `0.0.0.0:8765`. If you only open the Security Group and forget the Windows
> Firewall rule, you will spend a long time debugging a healthy server.

*Layer 1 — AWS Security Group:* EC2 → Security Groups → `yugen-mt5-sg` → Inbound rules → Edit:

- Add rule: Custom TCP, port `8765`, source `YOUR_PUBLIC_IP/32`. Never use `0.0.0.0/0` here.

*Layer 2 — Windows Defender Firewall* (PowerShell as Admin, inside the VPS):

```powershell
New-NetFirewallRule -DisplayName "Yugen MCP 8765" -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow
```

Diagnostics: `Get-NetTCPConnection -LocalPort 8765 -State Listen` confirms the server is
listening. `Get-NetFirewallRule -Direction Inbound -Enabled True | Get-NetFirewallPortFilter | Where-Object LocalPort -eq 8765` confirms the firewall rule exists. Empty output from the second command means the firewall rule is the problem.

**3. Generate a bearer token** (on the VPS):

See [Token generation](#token-generation) in the appendix.

**4. Start the server** (PowerShell on the VPS):

```powershell
$env:YUGEN_MT5_ALLOWED_SYMBOLS      = "EURUSD,XAUUSD"
$env:YUGEN_MT5_ALLOW_LIVE_TRADING   = "false"
$env:YUGEN_MT5_ALLOW_REAL_ACCOUNTS  = "false"

$env:YUGEN_MT5_REMOTE_ENABLED       = "true"
$env:YUGEN_MT5_REMOTE_HOST          = "0.0.0.0"              # public bind — tier "public"
$env:YUGEN_MT5_REMOTE_PORT          = "8765"
$env:YUGEN_MT5_REMOTE_BEARER_TOKEN  = "<YOUR_TOKEN>"
$env:YUGEN_MT5_REMOTE_ALLOWLIST     = "<YOUR_PUBLIC_IP>/32"  # your personal machine's IP
$env:YUGEN_MT5_REMOTE_ALLOW_INSECURE= "true"                 # acknowledges no-TLS risk

yugen-mt5-mcp run --transport remote --host 0.0.0.0 --port 8765
```

**5. Check server posture** (a second PowerShell window on the VPS):

```powershell
$env:YUGEN_MT5_REMOTE_ENABLED="true"; $env:YUGEN_MT5_REMOTE_HOST="0.0.0.0"
$env:YUGEN_MT5_REMOTE_ALLOW_INSECURE="true"; $env:YUGEN_MT5_REMOTE_BEARER_TOKEN="<YOUR_TOKEN>"
$env:YUGEN_MT5_REMOTE_ALLOWLIST="<YOUR_PUBLIC_IP>/32"; $env:YUGEN_MT5_ALLOWED_SYMBOLS="EURUSD,XAUUSD"
yugen-mt5-mcp doctor
```

Expected output: `remote_transport [WARN]` with `CRITICAL: "INSECURE: public bind without TLS
— token is transmitted in cleartext"`. This is correct — the doctor is working as designed.

See [Doctor verification](#doctor-verification) in the appendix for what each severity means.

**6. Connect the client** (from your personal machine):

Generate the config snippet:

```bash
yugen-mt5-mcp config remote --host <ELASTIC_IP> --port 8765 --token <YOUR_TOKEN> --scheme http
```

For Claude Code, add the server directly:

```bash
claude mcp add --transport http yugen-mt5-remote \
  "http://<ELASTIC_IP>:8765/mcp/" \
  --header "Authorization: Bearer <YOUR_TOKEN>"
```

Or add it manually to your client config:

```json
{
  "mcpServers": {
    "yugen-mt5-remote": {
      "url": "http://<ELASTIC_IP>:8765/mcp/",
      "headers": { "Authorization": "Bearer <YOUR_TOKEN>" }
    }
  }
}
```

See [curl verification](#curl-verification) in the appendix to test connectivity first.

**7. Verify, then tear down Phase A:**

Ask the agent something read-only (e.g. list symbols or run `doctor`). Once confirmed, shut
down the insecure phase immediately:

```powershell
# Stop the server (Ctrl+C in its window), then clean up:
Remove-NetFirewallRule -DisplayName "Yugen MCP 8765"
```

Remove the port 8765 inbound rule from the AWS Security Group as well.

### Phase B — TLS via Caddy

**1. Create a DNS A record:** In your DNS provider, add an A record pointing
`mcp.yourdomain.com` to `ELASTIC_IP`. Wait for propagation (`nslookup mcp.yourdomain.com`).

**2. Update the Security Group:** EC2 → `yugen-mt5-sg` → Inbound rules:

- Remove the port 8765 rule (it is no longer exposed directly).
- Add: HTTP port `80` from `0.0.0.0/0` — required for Let's Encrypt ACME challenge.
- Add: HTTPS port `443` from `YOUR_PUBLIC_IP/32` — restrict to your machine only.

**3. Open ports 80 and 443 in Windows Defender Firewall** (PowerShell as Admin on the VPS).
Caddy may create these rules automatically; if it does not, add them manually:

```powershell
New-NetFirewallRule -DisplayName "Caddy HTTP 80"  -Direction Inbound -Protocol TCP -LocalPort 80  -Action Allow
New-NetFirewallRule -DisplayName "Caddy HTTPS 443" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow
```

Remove these rules during cleanup, the same way you removed the port 8765 rule in Phase A.

**4. Install Caddy on the VPS** (PowerShell as Admin):

```powershell
# With winget (included in Windows Server 2022); or download the binary from caddyserver.com/download
winget install CaddyServer.Caddy
```

Create `C:\caddy\Caddyfile` using the sample from
[docs/remote-transport.md — Sample Caddyfile](remote-transport.md#sample-caddyfile).

Start Caddy:

```powershell
caddy run --config C:\caddy\Caddyfile
```

Caddy obtains and renews the Let's Encrypt certificate automatically. Leave it running in its
own window, or register it as a Windows service for production use.

**5. Start the server in secure mode** (loopback bind + TLS declared):

```powershell
$env:YUGEN_MT5_ALLOWED_SYMBOLS      = "EURUSD,XAUUSD"
$env:YUGEN_MT5_ALLOW_LIVE_TRADING   = "false"
$env:YUGEN_MT5_ALLOW_REAL_ACCOUNTS  = "false"

$env:YUGEN_MT5_REMOTE_ENABLED       = "true"
$env:YUGEN_MT5_REMOTE_HOST          = "127.0.0.1"        # loopback — tier trusted-local
$env:YUGEN_MT5_REMOTE_PORT          = "8765"
$env:YUGEN_MT5_REMOTE_BEARER_TOKEN  = "<YOUR_TOKEN>"
$env:YUGEN_MT5_REMOTE_TLS_TERMINATED= "true"             # declares that Caddy handles TLS
$env:YUGEN_MT5_REMOTE_ALLOWLIST     = "<YOUR_PUBLIC_IP>/32"

yugen-mt5-mcp run --transport remote --host 127.0.0.1 --port 8765
```

> **XFF allowlist gotcha:** When the server binds to loopback, it trusts the `X-Forwarded-For`
> header that Caddy sets, and evaluates the allowlist against your **real public IP** — not
> `127.0.0.1`. Set `YUGEN_MT5_REMOTE_ALLOWLIST` to `YOUR_PUBLIC_IP/32` (your personal
> machine's IP). If you set `127.0.0.1/32` (as some examples suggest), every request will
> be blocked with 403. For the conceptual explanation of why this works this way, see
> [docs/remote-transport.md — Trust-tier model](remote-transport.md#trust-tier-model).

**6. Verify posture:**

```powershell
yugen-mt5-mcp doctor
```

Expected: `remote_transport [OK]` — no CRITICAL. At most an INFO note about the allowlist.

**7. Connect the client** (from your personal machine):

```bash
yugen-mt5-mcp config remote --host mcp.yourdomain.com --port 443 --token <YOUR_TOKEN>
```

Or for Claude Code:

```bash
claude mcp add --transport http yugen-mt5-remote \
  "https://mcp.yourdomain.com/mcp/" \
  --header "Authorization: Bearer <YOUR_TOKEN>"
```

Client config JSON:

```json
{
  "mcpServers": {
    "yugen-mt5-remote": {
      "url": "https://mcp.yourdomain.com/mcp/",
      "headers": { "Authorization": "Bearer <YOUR_TOKEN>" }
    }
  }
}
```

Port 443 is implicit — do not include it in the URL. The token now travels encrypted from your
machine to Caddy.

### Production hardening

- **Inject env vars via a service**, not interactively. Use `--env-file .env` or register the
  server and Caddy as Windows services (e.g. with NSSM). Keep the `.env` file at restricted
  permissions and never commit it.
- **Do not enable trading until you have tested on demo.** Leave `YUGEN_MT5_ALLOW_LIVE_TRADING`
  and `YUGEN_MT5_ALLOW_REAL_ACCOUNTS` as `false` until you are confident in the setup. See
  [Security escalation](#security-escalation) for the step-by-step progression.
- **Tighten the allowlist** to the exact `/32` CIDR of your personal machine and review the
  SQLite audit log (`YUGEN_MT5_AUDIT_PATH`) periodically.

### Cleanup (avoid ongoing AWS costs)

- Stop or terminate the EC2 instance when not in use.
- **Release the Elastic IP** if you terminate the instance — unassociated Elastic IPs are
  billed separately.
- Delete the Security Group and key pair if you will not reuse them.
- Remove the Windows Firewall rules you created (ports 80, 443, and 8765 if Phase A was run).

---

## Security escalation

The server operates in three permission tiers. Escalate deliberately — do not skip tiers.

| Tier | Env vars required | Effect |
|------|------------------|--------|
| **Read-only** (default) | none | Market data, account state, position info; no order execution |
| **Demo + live trading** | `YUGEN_MT5_ALLOW_LIVE_TRADING=true` | Order execution enabled; demo accounts only |
| **Real account** | `YUGEN_MT5_ALLOW_REAL_ACCOUNTS=true` + call `acknowledge_real_account` MCP tool + `YUGEN_MT5_REAL_ACCOUNT_CONSENT` set | Real-account operations permitted; session-scoped acknowledgement |

**Notes:**

- `YUGEN_MT5_REAL_ACCOUNT_CONSENT` resets on every server restart. Each new session requires
  a fresh call to the `acknowledge_real_account` MCP tool before real-account operations proceed.
- The `acknowledge_real_account` tool must be called by the AI client at the start of each
  session where real-account operations are intended. This is a deliberate session-scoped gate,
  not a one-time configuration.
- The doctor's `real_account_consent` check reports a WARNING when ambient consent is active
  (`YUGEN_MT5_REAL_ACCOUNT_CONSENT` set in the environment) to keep the risk visible.

For the full env-var reference, see [Environment variables](#environment-variables) in the appendix.

---

## Reference appendix

### Environment variables

All `YUGEN_MT5_*` variables relevant to connection and security.

- `REMOTE_*` and trading-gate booleans such as `YUGEN_MT5_ALLOW_LIVE_TRADING` and
  `YUGEN_MT5_ALLOW_REAL_ACCOUNTS` are parsed as `true` / `false` (case-insensitive), with
  only `true` treated as truthy.
- `YUGEN_MT5_REAL_ACCOUNT_CONSENT` is different: it accepts `1`, `true`, `yes`, and `on`
  (case-insensitive) as truthy values.

**Connection and transport**

For the canonical `REMOTE_*` variable reference (`YUGEN_MT5_REMOTE_ENABLED`,
`YUGEN_MT5_REMOTE_HOST`, `YUGEN_MT5_REMOTE_PORT`, `YUGEN_MT5_REMOTE_BEARER_TOKEN`,
`YUGEN_MT5_REMOTE_TLS_TERMINATED`, `YUGEN_MT5_REMOTE_ALLOWLIST`,
`YUGEN_MT5_REMOTE_ALLOW_INSECURE`, `YUGEN_MT5_REMOTE_STATELESS_HTTP`, and
`YUGEN_MT5_REMOTE_PATH`), see
[docs/remote-transport.md — Environment variables](remote-transport.md#environment-variables).
All URL examples in this guide assume the default remote path `/mcp/`.

**Security and trading gates**

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `YUGEN_MT5_ALLOWED_SYMBOLS` | **Yes** | — | Comma-separated symbol allowlist, or `*` for all. Wildcard prints a startup warning but does not relax any trading gate. |
| `YUGEN_MT5_ALLOW_LIVE_TRADING` | No | `false` | Set `true` to enable order execution. When `false`, the server is read-only. |
| `YUGEN_MT5_ALLOW_REAL_ACCOUNTS` | No | `false` | Set `true` to permit real (non-demo) account operations. |
| `YUGEN_MT5_REAL_ACCOUNT_CONSENT` | No | — | Ambient consent token for real-account operations. Resets on every server restart; sets ambient pre-authorization. |
| `YUGEN_MT5_MAX_ORDER_VOLUME` | No | `1.0` | Maximum lot volume per single exposure-creating order. Set `unlimited` to disable (startup warning). |
| `YUGEN_MT5_MAX_SYMBOL_EXPOSURE` | No | `1.0` | Maximum cumulative open volume per symbol. Checked on open only. Set `unlimited` to disable (startup warning). |
| `YUGEN_MT5_AUDIT_PATH` | No | `var/audit.sqlite3` | Path to the SQLite audit database. **Use an absolute path with desktop clients.** |

---

### Token generation

Generate a cryptographically strong random token before enabling remote transport.

**On Linux / macOS / WSL:**

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Alternative using OpenSSL:

```bash
openssl rand -hex 32
```

**On Windows (PowerShell):**

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Store the token in your `.env` file or set it as an environment variable. Never commit it to
version control.

---

### Doctor verification

Run the built-in readiness check before connecting a client:

```powershell
yugen-mt5-mcp doctor
```

For JSON output (useful for scripting):

```powershell
yugen-mt5-mcp doctor --json
```

Use `OK` for a clean posture, `WARN` when the server still starts with a reviewable risk,
`CRITICAL` when the posture is unsafe (for example Phase A's intentional public HTTP test), and
`SKIPPED` when a check does not apply.

For the full command reference, exit-code behavior, and detailed remote posture examples, see
[docs/cli.md — doctor](cli.md#doctor) and
[docs/remote-transport.md — Doctor posture check](remote-transport.md#doctor-posture-check).

---

### curl verification

Test connectivity before configuring the AI client:

```bash
# HTTP (loopback / LAN / Phase A)
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer <YOUR_TOKEN>" \
  http://<HOST>:<PORT>/mcp/

# HTTPS (Phase B / production)
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer <YOUR_TOKEN>" \
  https://mcp.yourdomain.com/mcp/
```

Expected response: `200` or `405` (the server is reachable; `405` means the GET method is not
accepted on that endpoint, which is normal — MCP uses POST). A `401` means the token is wrong.
A timeout means a firewall rule is missing.

---

### AUDIT_PATH warning

The default audit path is `var/audit.sqlite3` (relative). When a desktop client (Claude Desktop,
Cursor, OpenCode) launches the server, it sets the working directory to the client's own
application directory — not the project root. The relative path then resolves to an unexpected
location, and the database may not be created where you expect.

**Always use an absolute path for `YUGEN_MT5_AUDIT_PATH` in desktop client configurations:**

```
YUGEN_MT5_AUDIT_PATH=C:\Users\YOUR_USERNAME\AppData\Local\Yugen\mt5-mcp\audit.sqlite3
```

The `yugen-mt5-mcp run --env-file` path (Method 1) is not affected because you control the
working directory when launching from a terminal. The AUDIT_PATH warning in the doctor output
(`audit_path [WARN]`) will appear if the path is not writable at startup.
