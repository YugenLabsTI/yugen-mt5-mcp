# CLI Reference

```
yugen-mt5-mcp <command> [options]
```

Bare invocation (no subcommand) is identical to `yugen-mt5-mcp run` in stdio mode. Existing client configs that reference only the script name continue to work without modification.

---

## Commands

- [`run`](#run) — Start the MCP server
- [`doctor`](#doctor) — Run readiness checks
- [`config`](#config) — Generate client configuration
- [`init`](#init) — Interactive configuration wizard
- [`version`](#version) — Print version information

---

## `run`

Start the MCP server.

```
yugen-mt5-mcp run [OPTIONS]
```

Default transport is `stdio`. Use `--transport remote` to start the HTTP transport (requires the `[remote]` extra).

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--transport`, `-t` | `stdio` | Transport mode: `stdio` or `remote`. |
| `--host` | `127.0.0.1` | Bind address for remote transport. Only used when `--transport remote`. |
| `--port`, `-p` | `8765` | Port for remote transport. Only used when `--transport remote`. |
| `--env-file` | _(none)_ | Load configuration from a dotenv file instead of exporting each variable by hand. Real environment variables take precedence over the file. |

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Server exited cleanly. |
| `1` | Invalid transport value, remote transport requested without `uvicorn` installed, or `--env-file` path not found. |

### Examples

```powershell
# Start in stdio mode (default)
yugen-mt5-mcp run

# Start in remote HTTP mode on the default loopback address
yugen-mt5-mcp run --transport remote

# Remote mode on a custom host and port
yugen-mt5-mcp run --transport remote --host 0.0.0.0 --port 9000

# Load configuration from a dotenv file (switch demo/real profiles easily)
yugen-mt5-mcp run --env-file ./demo.env
```

> **Production note:** when running as a service on a VPS, prefer letting the
> process manager inject the environment (systemd `EnvironmentFile=`, or
> `docker run --env-file`) over `--env-file`. Keep secret-bearing env files at
> `chmod 600` and never commit them.

Install the remote extra before using `--transport remote`:

```powershell
pip install "yugen-mt5-mcp[remote]"
```

---

## `doctor`

Run all readiness checks without starting the MCP server.

```
yugen-mt5-mcp doctor [OPTIONS]
```

Checks run in this order: `platform` → `config` → `audit_path` → `runtime_context` → `remote_transport` → `mt5_connection` → `mt5_account` → `real_account_consent`.

On non-Windows platforms, `mt5_connection` and `mt5_account` are reported as `SKIPPED` (not `FAILED`). All other checks run on all platforms.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--json` | `false` | Emit machine-readable JSON instead of a human-readable table. |

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | All checks passed (WARN and SKIPPED do not affect the exit code). |
| `1` | One or more checks returned `FAIL`. |

### Examples

```powershell
# Human-readable output
yugen-mt5-mcp doctor

# Machine-readable JSON (useful for scripting)
yugen-mt5-mcp doctor --json
```

### Sample output

```
yugen-mt5-mcp doctor — 2026-06-03 12:00:00 UTC

  platform              [OK     ]  Running on Windows
  config                [OK     ]  Configuration loaded
  audit_path            [OK     ]  Audit path is writable
  runtime_context       [OK     ]  Runtime context is valid
  remote_transport      [OK     ]  Remote transport not enabled
  mt5_connection        [OK     ]  MT5 terminal connected
  mt5_account           [OK     ]  Account info retrieved
  real_account_consent  [OK     ]  Demo account — no consent required

Overall: OK
```

---

## `config`

Generate a paste-ready MCP client configuration block.

```
yugen-mt5-mcp config <client> [OPTIONS]
```

Output goes to stdout by default. Use `--output <path>` to write to a file.

No personal paths or real credentials are included — env var values are generic placeholders that you fill in.

### Sub-commands

#### `config claude`

Print the Claude Desktop `mcpServers` configuration block.

```
yugen-mt5-mcp config claude [OPTIONS]
```

Merge the output into:
- **Windows**: `C:\Users\YOUR_USERNAME\AppData\Roaming\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

| Flag | Default | Description |
|------|---------|-------------|
| `--version`, `-v` | latest | Pin the package to a specific version (e.g. `0.1.0`). |
| `--output`, `-o` | stdout | Write the JSON to a file instead of printing it. |

```powershell
yugen-mt5-mcp config claude
yugen-mt5-mcp config claude --version 0.1.0
yugen-mt5-mcp config claude --output claude_config.json
```

#### `config cursor`

Print the Cursor `mcpServers` configuration block (same schema as Claude Desktop).

```
yugen-mt5-mcp config cursor [OPTIONS]
```

Merge into `~/.cursor/mcp.json`.

| Flag | Default | Description |
|------|---------|-------------|
| `--version`, `-v` | latest | Pin the package version. |
| `--output`, `-o` | stdout | Write to a file. |

```powershell
yugen-mt5-mcp config cursor
yugen-mt5-mcp config cursor --output ~/.cursor/mcp.json
```

#### `config opencode`

Print the OpenCode `mcp` configuration block.

```
yugen-mt5-mcp config opencode [OPTIONS]
```

Merge into `~/.config/opencode/config.json` (or `opencode.json` at project root).

| Flag | Default | Description |
|------|---------|-------------|
| `--version`, `-v` | latest | Pin the package version. |
| `--output`, `-o` | stdout | Write to a file. |

```powershell
yugen-mt5-mcp config opencode
```

#### `config remote`

Print an HTTP remote transport configuration block with a bearer token placeholder.

```
yugen-mt5-mcp config remote [OPTIONS]
```

Use this when the MCP client connects to a yugen-mt5-mcp server running on another machine (e.g. from WSL or macOS to a Windows MT5 host).

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `127.0.0.1` | Remote server host. |
| `--port` | `8765` | Remote server port. |
| `--token` | `<BEARER_TOKEN>` | Bearer token placeholder. |
| `--output`, `-o` | stdout | Write to a file. |

```powershell
yugen-mt5-mcp config remote
yugen-mt5-mcp config remote --host 192.168.1.100 --port 8765 --token my-secret-token
```

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Config printed or written successfully. |
| `1` | Unknown client or write error. |

---

## `init`

Interactive wizard to generate a `YUGEN_MT5_*` environment variable block.

```
yugen-mt5-mcp init [OPTIONS]
```

Prompts for: allowed symbols, demo/live mode, real account permission, max order volume, max symbol exposure, and audit path. Does NOT require MetaTrader 5 to be connected.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--json` | `false` | Emit JSON instead of `KEY=VALUE` pairs. |
| `--output`, `-o` | stdout | Write the output to a file (e.g. `.env`). |

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Wizard completed and output printed or written. |
| `1` | User cancelled or write error. |

### Examples

```powershell
# Interactive wizard, print to stdout
yugen-mt5-mcp init

# Write env block to a .env file
yugen-mt5-mcp init --output .env

# JSON output
yugen-mt5-mcp init --json
```

### Sample output

```
YUGEN_MT5_ALLOWED_SYMBOLS=EURUSD,XAUUSD
YUGEN_MT5_ALLOW_LIVE_TRADING=false
YUGEN_MT5_ALLOW_REAL_ACCOUNTS=false
YUGEN_MT5_MAX_ORDER_VOLUME=1.0
YUGEN_MT5_MAX_SYMBOL_EXPOSURE=1.0
```

---

## `version`

Print package version, Python version, and platform information.

```
yugen-mt5-mcp version
```

On Windows with MT5 connected, also prints the MT5 terminal build information.

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Always. |

### Sample output

```
yugen-mt5-mcp 0.1.0
Python 3.12.3 (main, ...) [MSC v.1940 64 bit (AMD64)]
Platform Windows-11-10.0.26100
MetaTrader5 terminal: C:\Program Files\MetaTrader 5\terminal64.exe (build 4755)
```
