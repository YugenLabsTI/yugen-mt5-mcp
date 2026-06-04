# Installation

This page covers all supported installation methods for `yugen-mt5-mcp`.

## Requirements

- Python 3.11 or 3.12
- Windows (required for MetaTrader 5 connectivity — the server will install and start on other platforms but MT5-dependent tools will be unavailable)
- MetaTrader 5 terminal open and logged in before starting the server

---

## Option 1: Run without installing (recommended for first-time use)

[uv](https://docs.astral.sh/uv/getting-started/installation/) runs the package directly from PyPI in an isolated environment — no install step needed.

```powershell
uvx yugen-mt5-mcp
```

The package is downloaded on first run and cached for subsequent runs. Use this for quick evaluation or when you do not want a persistent installation.

---

## Option 2: Install persistently with uv

```powershell
uv tool install yugen-mt5-mcp
```

After this, `yugen-mt5-mcp` is available as a global command. Upgrade with:

```powershell
uv tool upgrade yugen-mt5-mcp
```

---

## Option 3: Install with pip

```powershell
pip install yugen-mt5-mcp
```

Or with a version pin:

```powershell
pip install "yugen-mt5-mcp==0.1.0"
```

---

## Option 4: Install with remote transport support

The HTTP remote transport (for WSL, macOS, or VPS clients connecting to a Windows MT5) requires the `[remote]` extra, which pulls in `uvicorn`.

```powershell
pip install "yugen-mt5-mcp[remote]"
```

Or with uv:

```powershell
uv tool install "yugen-mt5-mcp[remote]"
```

---

## Platform notes

### Windows

`MetaTrader5` is automatically installed as a dependency on Windows (`sys_platform == 'win32'`). No manual step is needed.

### Linux / macOS

`MetaTrader5` is not installed on non-Windows platforms (the platform marker excludes it). The CLI, `doctor`, `config`, `init`, and `version` commands work normally. MT5-dependent doctor checks (`mt5_connection`, `mt5_account`) report `SKIPPED`.

---

## Verify the installation

```powershell
yugen-mt5-mcp doctor
```

This runs all readiness checks without starting the server. A healthy output looks like:

```
yugen-mt5-mcp doctor — 2026-06-03 12:00:00 UTC

  platform            [OK     ]  Running on Windows
  config              [OK     ]  Configuration loaded
  audit_path          [OK     ]  Audit path is writable
  runtime_context     [OK     ]  Runtime context is valid
  remote_transport    [OK     ]  Remote transport not enabled
  mt5_connection      [OK     ]  MT5 terminal connected
  mt5_account         [OK     ]  Account info retrieved
  real_account_consent [OK    ]  Demo account — no consent required

Overall: OK
```

---

## Next steps

- See [docs/cli.md](cli.md) for all CLI commands and options.
- See [docs/remote-transport.md](remote-transport.md) for remote transport setup.
- See the [README](../README.md) for client configuration (Claude Desktop, Cursor, OpenCode).
