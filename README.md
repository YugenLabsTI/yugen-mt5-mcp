# yugen-mt5-mcp

A secure, extensible MCP server for MetaTrader with trading, chart objects, risk controls, and VPS-ready deployment.

## Foundation status

PR1 bootstraps the Python package, safe transport configuration defaults, and the SQLite audit base.

### Current guarantees

- Local `stdio` is the default transport.
- Remote transport is opt-in and rejected unless bearer auth, TLS termination, and a non-wildcard bind are configured.
- Audit events are persisted to SQLite with recursive secret redaction for tokens, passwords, and authorization headers.
