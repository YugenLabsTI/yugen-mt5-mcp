# yugen-mt5-mcp

Secure MCP server foundations for MetaTrader 5 with audited trading controls, loopback chart bridging, and a hardened remote path for VPS use.

## Quick path

1. Start in local `stdio` mode by default.
2. Enable remote mode only behind Caddy TLS termination with a bearer token, private/loopback bind, and explicit allowlist.
3. Treat real-account trading as session-scoped risk acceptance that resets on restart.

## Transport modes

MCP transport defines how an MCP client talks to this server. It does not change
the tools themselves; it changes the communication channel.

| Mode | Default | Requirements | Notes |
|------|---------|--------------|-------|
| `stdio` | Yes | Client starts the local process | No TCP listener is opened; the client exchanges JSON over the process stdin/stdout pipes. |
| `remote` | No | `tls_terminated=true`, `reverse_proxy="caddy"`, bearer token, non-public bind, non-empty allowlist | Intended for VPS deployments with Caddy terminating TLS and proxying to the local MCP process. |

Use `stdio` when the MCP client and MT5 terminal are on the same Windows host.
Use `remote` only when another machine or environment, such as WSL or a VPS
client, must reach the Windows-hosted server over a network boundary.

## Run on Windows with stdio

1. Open MetaTrader 5 and log into a demo account.
2. Install the package in editable mode:

   ```powershell
   python -m pip install -e ".[dev]"
   ```

3. Choose the symbol allowlist for reads and trading:

   ```powershell
   $env:YUGEN_MT5_ALLOWED_SYMBOLS="EURUSD,XAUUSD"
   ```

   `*` allows every symbol for reads and trading:

   ```powershell
   $env:YUGEN_MT5_ALLOWED_SYMBOLS="*"
   ```

   Wildcard mode prints a warning at startup. It does not relax live-trading,
   real-account, volume, or exposure gates.

4. To place demo orders, explicitly enable live trading and allow the trading
   symbol. Use `true` / `false` values:

   ```powershell
   $env:YUGEN_MT5_ALLOWED_SYMBOLS="Boom 1000 Index"
   $env:YUGEN_MT5_ALLOW_LIVE_TRADING="true"
   $env:YUGEN_MT5_ALLOW_REAL_ACCOUNTS="false"
   ```

   `YUGEN_MT5_ALLOW_REAL_ACCOUNTS="true"` is only for real accounts. Demo
   accounts do not need it.

5. (Optional) Tune the risk limits. Both default to `1.0` when unset:

   ```powershell
   $env:YUGEN_MT5_MAX_ORDER_VOLUME="2.0"       # max volume of a single order
   $env:YUGEN_MT5_MAX_SYMBOL_EXPOSURE="5.0"    # max cumulative volume per symbol
   ```

   `max_order_volume` caps one order; `max_symbol_exposure` caps the total
   open volume across all positions in the same symbol. Set either to
   `unlimited` (or a negative number) to disable that gate — this prints a
   warning at startup so the relaxed limit stays visible. An unparsable value
   stops startup with a clear error instead of silently defaulting.

6. Start the stdio MCP server:

   ```powershell
   python -m yugen_mt5_mcp
   ```

   If installed as a script, this is equivalent:

   ```powershell
   yugen-mt5-mcp
   ```

The server connects to the already-open local MT5 terminal through the official
MetaTrader5 Python IPC session. It does not need the account password because
the terminal is already authenticated.

### Claude Desktop example

Claude Desktop should launch the server with a writable audit path. Prefer an
absolute path so the server does not depend on Claude's process working
directory:

```json
{
  "mcpServers": {
    "yugen-mt5": {
      "command": "C:\\Users\\sgg10\\AppData\\Local\\Python\\pythoncore-3.14-64\\python.exe",
      "args": ["-m", "yugen_mt5_mcp"],
      "cwd": "C:\\Users\\sgg10\\Documents\\yugen-mt5-mcp",
      "env": {
        "YUGEN_MT5_ALLOWED_SYMBOLS": "Boom 1000 Index",
        "YUGEN_MT5_ALLOW_LIVE_TRADING": "true",
        "YUGEN_MT5_ALLOW_REAL_ACCOUNTS": "false",
        "YUGEN_MT5_MAX_ORDER_VOLUME": "2.0",
        "YUGEN_MT5_MAX_SYMBOL_EXPOSURE": "5.0",
        "YUGEN_MT5_AUDIT_PATH": "C:\\Users\\sgg10\\AppData\\Local\\Yugen\\mt5-mcp\\audit.sqlite3"
      }
    }
  }
}
```

`YUGEN_MT5_AUDIT_PATH` defaults to `var/audit.sqlite3`. Set it explicitly for
desktop clients so audit storage lands in a user-writable directory.

Remote startup is rejected if it tries to:

- skip bearer auth,
- skip TLS termination,
- bind to wildcard/public IPs,
- allow every client (`0.0.0.0/0` or equivalent), or
- bypass the documented Caddy reverse-proxy path.

## VPS Caddy path

Recommended topology:

```text
Agent -> HTTPS/WSS -> Caddy (TLS) -> 127.0.0.1:<mcp-port> -> yugen-mt5-mcp
```

Keep the MCP process on a loopback or private bind. Caddy is the public edge; the MCP server is not.

## Trading safety model

| Control | Behavior |
|---------|----------|
| Real-account acknowledgement | Required only for the current server/agent session. |
| Restart semantics | Any server or agent restart clears the acknowledgement. |
| Allowed symbols / account modes | Enforced before MT5 calls. |
| Volume / exposure limits | Checked before order submission. Configurable via `YUGEN_MT5_MAX_ORDER_VOLUME` / `YUGEN_MT5_MAX_SYMBOL_EXPOSURE` (default `1.0`; `unlimited` disables with a startup warning). |
| Audit trail | SQLite append-only events with token/secret redaction. |

## Demo smoke controls

Live smoke coverage is opt-in and demo-only.

Required environment variables:

- `YUGEN_MT5_ENABLE_DEMO_SMOKE=1`
- `YUGEN_MT5_DEMO_SMOKE_ACK=demo-only`

Optional environment variables:

- `YUGEN_MT5_DEMO_SMOKE_SYMBOLS=EURUSD,XAUUSD`
- `YUGEN_MT5_DEMO_SMOKE_MAX_VOLUME=0.01`

Guardrails:

- real accounts are rejected,
- symbols must be explicitly allowed,
- smoke volume must stay `> 0` and `<= 0.01` lots.
