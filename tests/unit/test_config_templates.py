"""Unit tests for config_templates module.

Verifies:
- All four template functions return JSON-serialisable dicts.
- No personal paths leak into the output.
- Version pinning works correctly for claude_config / cursor_config.
- Remote config reflects custom host/port/token.
"""

from __future__ import annotations

import json

import pytest

from yugen_mt5_mcp.config_templates import (
    claude_config,
    cursor_config,
    opencode_config,
    remote_config,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PERSONAL_PATH_MARKERS = [
    "sgg10",
    "C:\\Users\\",
    "/home/sgg10",
    "/Users/sgg10",
]


def _assert_no_personal_paths(data: str) -> None:
    for marker in _PERSONAL_PATH_MARKERS:
        assert marker not in data, f"Personal path marker {marker!r} found in output"


# ---------------------------------------------------------------------------
# JSON-serialisability
# ---------------------------------------------------------------------------


def test_claude_config_is_json_serialisable() -> None:
    dumped = json.dumps(claude_config())
    assert dumped  # non-empty string


def test_cursor_config_is_json_serialisable() -> None:
    dumped = json.dumps(cursor_config())
    assert dumped


def test_opencode_config_is_json_serialisable() -> None:
    dumped = json.dumps(opencode_config())
    assert dumped


def test_remote_config_is_json_serialisable() -> None:
    dumped = json.dumps(remote_config())
    assert dumped


# ---------------------------------------------------------------------------
# No personal paths
# ---------------------------------------------------------------------------


def test_claude_config_has_no_personal_paths() -> None:
    _assert_no_personal_paths(json.dumps(claude_config()))


def test_cursor_config_has_no_personal_paths() -> None:
    _assert_no_personal_paths(json.dumps(cursor_config()))


def test_opencode_config_has_no_personal_paths() -> None:
    _assert_no_personal_paths(json.dumps(opencode_config()))


def test_remote_config_has_no_personal_paths() -> None:
    _assert_no_personal_paths(json.dumps(remote_config()))


# ---------------------------------------------------------------------------
# claude_config structure and version pinning
# ---------------------------------------------------------------------------


def test_claude_config_structure() -> None:
    cfg = claude_config()
    assert "mcpServers" in cfg
    server = cfg["mcpServers"]["yugen-mt5"]  # type: ignore[index]
    assert server["command"] == "uvx"
    assert isinstance(server["args"], list)
    assert isinstance(server["env"], dict)


def test_claude_config_no_version_uses_bare_pkg() -> None:
    cfg = claude_config()
    args = cfg["mcpServers"]["yugen-mt5"]["args"]  # type: ignore[index]
    assert args == ["yugen-mt5-mcp"]


def test_claude_config_version_is_pinned_in_args() -> None:
    cfg = claude_config("0.2.0")
    args = cfg["mcpServers"]["yugen-mt5"]["args"]  # type: ignore[index]
    assert "yugen-mt5-mcp@0.2.0" in args


def test_claude_config_env_keys_present() -> None:
    env = claude_config()["mcpServers"]["yugen-mt5"]["env"]  # type: ignore[index]
    required_keys = [
        "YUGEN_MT5_ALLOWED_SYMBOLS",
        "YUGEN_MT5_ALLOW_LIVE_TRADING",
        "YUGEN_MT5_ALLOW_REAL_ACCOUNTS",
        "YUGEN_MT5_MAX_ORDER_VOLUME",
        "YUGEN_MT5_MAX_SYMBOL_EXPOSURE",
    ]
    for key in required_keys:
        assert key in env, f"Missing env key: {key}"


# ---------------------------------------------------------------------------
# cursor_config — same schema as claude_config
# ---------------------------------------------------------------------------


def test_cursor_config_has_mcp_servers_key() -> None:
    cfg = cursor_config()
    assert "mcpServers" in cfg


def test_cursor_config_matches_schema() -> None:
    cfg = cursor_config()
    server = cfg["mcpServers"]["yugen-mt5"]  # type: ignore[index]
    assert server["command"] == "uvx"
    assert isinstance(server["args"], list)
    assert isinstance(server["env"], dict)


def test_cursor_config_version_pinned() -> None:
    cfg = cursor_config("1.0.0")
    args = cfg["mcpServers"]["yugen-mt5"]["args"]  # type: ignore[index]
    assert "yugen-mt5-mcp@1.0.0" in args


# ---------------------------------------------------------------------------
# opencode_config structure
# ---------------------------------------------------------------------------


def test_opencode_config_has_mcp_key() -> None:
    cfg = opencode_config()
    assert "mcp" in cfg


def test_opencode_config_server_structure() -> None:
    cfg = opencode_config()
    server = cfg["mcp"]["yugen-mt5"]  # type: ignore[index]
    assert server["type"] == "local"
    assert isinstance(server["command"], list)
    assert "uvx" in server["command"]
    assert isinstance(server["environment"], dict)
    assert server["enabled"] is True


def test_opencode_config_version_in_command() -> None:
    cfg = opencode_config("0.3.0")
    command = cfg["mcp"]["yugen-mt5"]["command"]  # type: ignore[index]
    assert any("yugen-mt5-mcp@0.3.0" in part for part in command)


# ---------------------------------------------------------------------------
# remote_config structure
# ---------------------------------------------------------------------------


def test_remote_config_default_structure() -> None:
    cfg = remote_config()
    assert "mcpServers" in cfg
    server = cfg["mcpServers"]["yugen-mt5-remote"]  # type: ignore[index]
    assert "url" in server
    assert "headers" in server
    assert "Authorization" in server["headers"]


def test_remote_config_default_has_placeholder_token() -> None:
    cfg = remote_config()
    auth = cfg["mcpServers"]["yugen-mt5-remote"]["headers"]["Authorization"]  # type: ignore[index]
    assert "<BEARER_TOKEN>" in auth


def test_remote_config_reflects_custom_host_port() -> None:
    cfg = remote_config(host="1.2.3.4", port=9000)
    url = cfg["mcpServers"]["yugen-mt5-remote"]["url"]  # type: ignore[index]
    assert "1.2.3.4" in url
    assert "9000" in url


def test_remote_config_reflects_custom_token() -> None:
    cfg = remote_config(token="my-secret-token")
    auth = cfg["mcpServers"]["yugen-mt5-remote"]["headers"]["Authorization"]  # type: ignore[index]
    assert "my-secret-token" in auth
