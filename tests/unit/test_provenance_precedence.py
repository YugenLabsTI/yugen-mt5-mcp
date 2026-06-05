"""WU-1 — Precedence regression test lock.

Lock _resolve_env precedence BEFORE the provenance refactor in WU-3.
These tests must stay green through all subsequent work units.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from yugen_mt5_mcp.cli import _resolve_env

# ---------------------------------------------------------------------------
# T1: os.environ wins over env-file when key present in both
# ---------------------------------------------------------------------------


def test_os_environ_wins_over_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key present in both env-file and os.environ resolves to the os.environ value."""
    env_file = tmp_path / "test.env"
    env_file.write_text("YUGEN_MT5_ALLOW_LIVE_TRADING=false\n")
    monkeypatch.setenv("YUGEN_MT5_ALLOW_LIVE_TRADING", "true")

    result = _resolve_env(env_file)

    assert result["YUGEN_MT5_ALLOW_LIVE_TRADING"] == "true"


# ---------------------------------------------------------------------------
# T2: env-file-only value is present when key absent from os.environ
# ---------------------------------------------------------------------------


def test_env_file_only_value_is_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key present only in env-file is present in the merged result."""
    env_file = tmp_path / "test.env"
    env_file.write_text("YUGEN_MT5_ALLOW_LIVE_TRADING=true\n")
    monkeypatch.delenv("YUGEN_MT5_ALLOW_LIVE_TRADING", raising=False)

    result = _resolve_env(env_file)

    assert result["YUGEN_MT5_ALLOW_LIVE_TRADING"] == "true"


# ---------------------------------------------------------------------------
# T3: key absent from both sources is absent from merged dict
# ---------------------------------------------------------------------------


def test_no_sources_key_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key absent from both env-file and os.environ is absent from the merged dict."""
    env_file = tmp_path / "test.env"
    env_file.write_text("SOME_OTHER_KEY=irrelevant\n")
    monkeypatch.delenv("YUGEN_MT5_ALLOW_LIVE_TRADING", raising=False)

    result = _resolve_env(env_file)

    assert "YUGEN_MT5_ALLOW_LIVE_TRADING" not in result


# ---------------------------------------------------------------------------
# T4: merged dict is identical to star-merge {**file_values, **os.environ}
# ---------------------------------------------------------------------------


def test_resolve_env_merged_dict_is_identical_to_star_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Result must be byte-for-bit identical to {**file_values, **os.environ}."""
    env_file = tmp_path / "test.env"
    env_file.write_text(
        "YUGEN_MT5_ALLOW_LIVE_TRADING=false\n"
        "YUGEN_MT5_FILE_ONLY_KEY=from_file\n"
    )
    monkeypatch.setenv("YUGEN_MT5_ALLOW_LIVE_TRADING", "true")
    monkeypatch.setenv("YUGEN_MT5_ENV_ONLY_KEY", "from_env")

    result = _resolve_env(env_file)

    # Construct expected via the exact same star-merge logic
    from dotenv import dotenv_values  # noqa: PLC0415

    file_values = {k: v for k, v in dotenv_values(env_file).items() if v is not None}
    expected = {**file_values, **os.environ}

    assert result == expected
