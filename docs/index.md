# Documentation Index

> [!TIP]
> 🇪🇸 **¿Prefieres leer en español?** Toda la documentación está disponible en español dentro de [`docs/es/`](es/), y el README en [`README.es.md`](../README.es.md). Cada página en español enlaza de vuelta a su versión en inglés.
>
> 🇬🇧 All documentation is available in both **English** (this folder) and **Spanish** ([`docs/es/`](es/)).

This page is your starting point for the `yugen-mt5-mcp` documentation. It explains what each document covers and the recommended reading order depending on who you are.

## Available languages

| Document | English | Español |
|----------|---------|---------|
| Project overview & quick start | [README.md](../README.md) | [README.es.md](../README.es.md) |
| Installation | [install.md](install.md) | [es/install.md](es/install.md) |
| Connection methods | [connection-methods.md](connection-methods.md) | [es/connection-methods.md](es/connection-methods.md) |
| CLI reference | [cli.md](cli.md) | [es/cli.md](es/cli.md) |
| Remote transport deployment | [remote-transport.md](remote-transport.md) | [es/remote-transport.md](es/remote-transport.md) |

## How to read this documentation

### I'm a new user — I just want to connect my AI client

1. Start with the [README](../README.md) — quick start, prerequisites, and ready-to-paste client configs (Claude Desktop, Cursor, OpenCode).
2. If you need more installation detail, read [install.md](install.md) — all install variants (uvx, uv tool, pip, `[remote]` extra) and platform notes.
3. Then follow [connection-methods.md](connection-methods.md) and pick your method: most users want **Method 2 (STDIO via uvx)**.
4. Validate everything with `yugen-mt5-mcp doctor` — see [cli.md](cli.md) for the full command reference.

### My AI client and MT5 are on different machines (WSL, macOS, VPS)

1. Read [connection-methods.md](connection-methods.md) — **Method 3** for same-network setups (WSL/macOS → Windows host) or **Method 4** for a public VPS with TLS.
2. Then go deeper with [remote-transport.md](remote-transport.md) — environment variables, the trust-tier security model, TLS termination (Caddy, nginx, Cloudflare), and the IP allowlist.

### I want to automate or script the server

Read [cli.md](cli.md) — every command (`run`, `doctor`, `config`, `init`, `version`), its flags, exit codes, and JSON output modes.

### I'm a contributor

1. The [README — For Contributors](../README.md#for-contributors) section covers clone, editable install, tests, and linting.
2. [connection-methods.md — Method 1](connection-methods.md#method-1--stdio-via-editable-install) explains how to run the server from source.

## Document summaries

- **[install.md](install.md)** — All supported installation methods, platform notes (Windows vs Linux/macOS), and how to verify the install with `doctor`.
- **[connection-methods.md](connection-methods.md)** — The complete connection guide: 4 methods from local STDIO to a hardened public VPS, plus a reference appendix (token generation, doctor/curl verification, AUDIT_PATH warning) and the security escalation tiers.
- **[cli.md](cli.md)** — Full CLI reference with options, exit codes, and sample output for every command.
- **[remote-transport.md](remote-transport.md)** — Deployment guide for the HTTP remote transport: env vars, trust tiers, TLS providers, WSL/Windows interop, and the security summary.

> [!NOTE]
> Whenever the English and Spanish versions differ, the **English version is the source of truth**. Si encuentras una discrepancia entre versiones, la versión en inglés prevalece — y agradecemos que reportes la diferencia abriendo un issue.
