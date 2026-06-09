<!-- mcp-name: io.github.yugenlabsti/yugen-mt5-mcp -->

# yugen-mt5-mcp

Secure, auditable MCP server for MetaTrader 5 — gives AI clients controlled access to market data, account state, and trade execution through a hardened gate with symbol allowlists, volume limits, and an append-only audit trail.

## Quick Start (for users)

### Prerequisites

- Windows with MetaTrader 5 installed and logged into a demo account
- [uv](https://docs.astral.sh/uv/getting-started/installation/) installed

### Run without installing

```powershell
uvx yugen-mt5-mcp
```

### Install persistently

```powershell
uv tool install yugen-mt5-mcp
yugen-mt5-mcp
```

### Validate your setup

```powershell
yugen-mt5-mcp doctor
```

This runs all readiness checks (config, MT5 connection, audit path, transport) without starting the server.

---

## Client Configuration

> For the complete connection guide covering all 4 methods (STDIO, LAN remote, VPS/TLS),
> see [docs/connection-methods.md](docs/connection-methods.md).

### Claude Desktop

Add the following to your Claude Desktop config file.

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

You can also generate this block automatically:

```powershell
yugen-mt5-mcp config claude
```

### Cursor

Add the following to `~/.cursor/mcp.json`:

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
        "YUGEN_MT5_MAX_SYMBOL_EXPOSURE": "1.0"
      }
    }
  }
}
```

```powershell
yugen-mt5-mcp config cursor
```

### OpenCode

Add the following to `~/.config/opencode/config.json`:

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
        "YUGEN_MT5_MAX_SYMBOL_EXPOSURE": "1.0"
      },
      "enabled": true
    }
  }
}
```

```powershell
yugen-mt5-mcp config opencode
```

---

## Configuration (Environment Variables)

All configuration is via `YUGEN_MT5_*` environment variables. You can generate an env block interactively:

```powershell
yugen-mt5-mcp init
```

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `YUGEN_MT5_ALLOWED_SYMBOLS` | **Yes** | — | Comma-separated symbol allowlist, or `*` for all. Wildcard prints a startup warning but does not relax any trading gate. |
| `YUGEN_MT5_ALLOW_LIVE_TRADING` | No | `false` | Set `true` to enable order execution. When `false` the server is read-only. |
| `YUGEN_MT5_ALLOW_REAL_ACCOUNTS` | No | `false` | Set `true` to permit real (non-demo) account operations. Demo accounts do not need this. |
| `YUGEN_MT5_MAX_ORDER_VOLUME` | No | `1.0` | Max lot volume per single exposure-creating order. Does not apply to closing or modifying. Set `unlimited` to disable (startup warning). |
| `YUGEN_MT5_MAX_SYMBOL_EXPOSURE` | No | `1.0` | Max cumulative open volume per symbol. Checked only on open. Set `unlimited` to disable (startup warning). |
| `YUGEN_MT5_AUDIT_PATH` | No | `var/audit.sqlite3` | Path to the SQLite audit database. Use an absolute path with desktop clients. |
| `YUGEN_MT5_REAL_ACCOUNT_CONSENT` | No | — | Explicit consent token for real-account operations. Resets on every restart. |
| `YUGEN_MT5_REMOTE_ENABLED` | No | `false` | Set `true` to start the HTTP remote transport. Requires `[remote]` extra. |
| `YUGEN_MT5_REMOTE_HOST` | No | `127.0.0.1` | Bind host for remote transport. Use `0.0.0.0` for LAN/VPS (requires TLS termination). |
| `YUGEN_MT5_REMOTE_PORT` | No | `8765` | Port for remote transport. |
| `YUGEN_MT5_REMOTE_BEARER_TOKEN` | No | — | Bearer token for remote transport auth. Required when `YUGEN_MT5_REMOTE_ENABLED=true`. |

### Trading safety model

| Control | Behavior |
|---------|----------|
| Real-account acknowledgement | Session-scoped. Clears on every server restart. |
| Allowed symbols / account modes | Enforced before MT5 calls. |
| Volume / exposure limits | Applied to opening orders only. Closing and modifying are never capped. |
| Audit trail | SQLite append-only log with token and secret redaction. |

---

## Remote Transport (WSL / Mac to Windows MT5)

When your AI client runs in WSL, macOS, or a VPS and MetaTrader 5 is on a Windows host, use the HTTP remote transport:

```powershell
# On the Windows host:
$env:YUGEN_MT5_REMOTE_ENABLED="true"
$env:YUGEN_MT5_REMOTE_BEARER_TOKEN="your-secret-token"
yugen-mt5-mcp run --transport remote

# Generate a client config block pointing at the Windows host:
yugen-mt5-mcp config remote --host 192.168.1.100 --port 8765 --token your-secret-token
```

Install the remote extra first:

```powershell
uv tool install "yugen-mt5-mcp[remote]"
```

See [docs/remote-transport.md](docs/remote-transport.md) for the full deployment guide, security model, and TLS setup.
For the step-by-step VPS (EC2 + Caddy/TLS) walkthrough, see [docs/connection-methods.md — Method 4](docs/connection-methods.md#method-4--remote-vps--caddytls).

---

## For Contributors

### Clone and install in editable mode

```powershell
git clone https://github.com/YugenLabsTI/yugen-mt5-mcp.git
cd yugen-mt5-mcp
python -m pip install -e ".[dev]"
```

### Run the test suite

```powershell
pytest
```

MT5-dependent tests are automatically skipped on non-Windows platforms.

### Run linting and type checks

```powershell
ruff check src tests
mypy
```

### Start the server locally

```powershell
$env:YUGEN_MT5_ALLOWED_SYMBOLS="EURUSD,XAUUSD"
yugen-mt5-mcp run
```

For all CLI options see [docs/cli.md](docs/cli.md). For installation variants see [docs/install.md](docs/install.md).

---

## License

Apache-2.0 — see [LICENSE.md](LICENSE.md). Copyright Yugen Labs S.A.S.
