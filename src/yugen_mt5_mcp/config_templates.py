"""Paste-ready MCP client configuration builders.

Each function returns a plain Python dict that is JSON-serialisable with
``json.dumps()``.  No personal paths, no hardcoded usernames.  All values
that the user must supply are represented by generic placeholders.
"""

from __future__ import annotations

_DEFAULT_ENV: dict[str, str] = {
    "YUGEN_MT5_ALLOWED_SYMBOLS": "EURUSD,XAUUSD",
    "YUGEN_MT5_ALLOW_LIVE_TRADING": "false",
    "YUGEN_MT5_ALLOW_REAL_ACCOUNTS": "false",
    "YUGEN_MT5_MAX_ORDER_VOLUME": "1.0",
    "YUGEN_MT5_MAX_SYMBOL_EXPOSURE": "1.0",
}

_PKG = "yugen-mt5-mcp"


def _uvx_args(version: str | None) -> list[str]:
    """Return the ``uvx`` args list, pinning to *version* when given."""
    if version:
        return [f"{_PKG}@{version}"]
    return [_PKG]


def claude_config(version: str | None = None) -> dict[str, object]:
    """Return a Claude Desktop ``mcpServers`` configuration block.

    Args:
        version: Optional package version to pin, e.g. ``"0.2.0"``.
                 When omitted the latest published version is used.

    Returns:
        A JSON-serialisable dict ready to merge into
        ``~/Library/Application Support/Claude/claude_desktop_config.json``
        (macOS) or the platform-equivalent path.
    """
    return {
        "mcpServers": {
            "yugen-mt5": {
                "command": "uvx",
                "args": _uvx_args(version),
                "env": dict(_DEFAULT_ENV),
            }
        }
    }


def cursor_config(version: str | None = None) -> dict[str, object]:
    """Return a Cursor ``mcpServers`` configuration block.

    Cursor uses the same MCP JSON schema as Claude Desktop.

    Args:
        version: Optional package version to pin.

    Returns:
        A JSON-serialisable dict ready to merge into ``~/.cursor/mcp.json``.
    """
    return {
        "mcpServers": {
            "yugen-mt5": {
                "command": "uvx",
                "args": _uvx_args(version),
                "env": dict(_DEFAULT_ENV),
            }
        }
    }


def opencode_config(version: str | None = None) -> dict[str, object]:
    """Return an OpenCode ``mcp`` configuration block.

    OpenCode uses a top-level ``"mcp"`` key in
    ``~/.config/opencode/config.json`` (or ``opencode.json`` at project root).
    Each server entry follows the schema::

        {
            "type": "local",
            "command": ["uvx", "yugen-mt5-mcp"],
            "environment": { ... },
            "enabled": true
        }

    NOTE: Verify this format against the current OpenCode docs at
    https://opencode.ai/docs/mcp-servers before committing to production use.
    The schema was correct as of June 2026.

    Args:
        version: Optional package version to pin.
    """
    return {
        "mcp": {
            "yugen-mt5": {
                "type": "local",
                "command": ["uvx"] + _uvx_args(version),
                "environment": dict(_DEFAULT_ENV),
                "enabled": True,
            }
        }
    }


def remote_config(
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str = "<BEARER_TOKEN>",
) -> dict[str, object]:
    """Return a remote-transport ``mcpServers`` block.

    Suitable for any MCP client that supports HTTP transport with bearer-token
    authentication.

    Args:
        host:  The host where the yugen-mt5-mcp remote server is running.
        port:  The port the remote server is listening on.
        token: The bearer token used in the ``Authorization`` header.
               Defaults to a placeholder; replace with a real token.

    Returns:
        A JSON-serialisable dict.
    """
    return {
        "mcpServers": {
            "yugen-mt5-remote": {
                "url": f"https://{host}:{port}/mcp",
                "headers": {
                    "Authorization": f"Bearer {token}",
                },
            }
        }
    }
