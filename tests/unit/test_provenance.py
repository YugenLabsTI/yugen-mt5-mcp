"""WU-2 — Tests for provenance.py leaf module.

TDD: tests written BEFORE the production module exists.
"""
from __future__ import annotations

from yugen_mt5_mcp.provenance import SAFETY_CRITICAL_KEYS, ConfigSource, derive_provenance

# ---------------------------------------------------------------------------
# T1: key in os_environ → OS_ENVIRON
# ---------------------------------------------------------------------------


def test_key_in_os_environ_returns_os_environ() -> None:
    result = derive_provenance(
        file_values={},
        os_environ={"YUGEN_MT5_ALLOW_LIVE_TRADING": "true"},
        tracked_keys=("YUGEN_MT5_ALLOW_LIVE_TRADING",),
    )
    assert result["YUGEN_MT5_ALLOW_LIVE_TRADING"] is ConfigSource.OS_ENVIRON


# ---------------------------------------------------------------------------
# T2: key in file only → ENV_FILE
# ---------------------------------------------------------------------------


def test_key_in_file_only_returns_env_file() -> None:
    result = derive_provenance(
        file_values={"YUGEN_MT5_ALLOW_LIVE_TRADING": "true"},
        os_environ={},
        tracked_keys=("YUGEN_MT5_ALLOW_LIVE_TRADING",),
    )
    assert result["YUGEN_MT5_ALLOW_LIVE_TRADING"] is ConfigSource.ENV_FILE


# ---------------------------------------------------------------------------
# T3: key absent from both → DEFAULT
# ---------------------------------------------------------------------------


def test_key_absent_returns_default() -> None:
    result = derive_provenance(
        file_values={},
        os_environ={},
        tracked_keys=("YUGEN_MT5_ALLOW_LIVE_TRADING",),
    )
    assert result["YUGEN_MT5_ALLOW_LIVE_TRADING"] is ConfigSource.DEFAULT


# ---------------------------------------------------------------------------
# T4: key in BOTH → OS_ENVIRON (regression)
# ---------------------------------------------------------------------------


def test_key_in_both_returns_os_environ() -> None:
    result = derive_provenance(
        file_values={"YUGEN_MT5_ALLOW_LIVE_TRADING": "false"},
        os_environ={"YUGEN_MT5_ALLOW_LIVE_TRADING": "true"},
        tracked_keys=("YUGEN_MT5_ALLOW_LIVE_TRADING",),
    )
    assert result["YUGEN_MT5_ALLOW_LIVE_TRADING"] is ConfigSource.OS_ENVIRON


# ---------------------------------------------------------------------------
# T5: empty sources → all tracked keys default to DEFAULT
# ---------------------------------------------------------------------------


def test_empty_sources_all_keys_default() -> None:
    keys = (
        "YUGEN_MT5_ALLOW_LIVE_TRADING",
        "YUGEN_MT5_ALLOW_REAL_ACCOUNTS",
        "YUGEN_MT5_REAL_ACCOUNT_CONSENT",
    )
    result = derive_provenance(
        file_values={},
        os_environ={},
        tracked_keys=keys,
    )
    for key in keys:
        assert result[key] is ConfigSource.DEFAULT


# ---------------------------------------------------------------------------
# ConfigSource values are the expected strings
# ---------------------------------------------------------------------------


def test_config_source_values() -> None:
    assert ConfigSource.OS_ENVIRON.value == "os.environ"
    assert ConfigSource.ENV_FILE.value == "env-file"
    assert ConfigSource.DEFAULT.value == "default"


# ---------------------------------------------------------------------------
# SAFETY_CRITICAL_KEYS contains the 3 gate keys
# ---------------------------------------------------------------------------


def test_safety_critical_keys_contains_gate_keys() -> None:
    assert "YUGEN_MT5_ALLOW_LIVE_TRADING" in SAFETY_CRITICAL_KEYS
    assert "YUGEN_MT5_ALLOW_REAL_ACCOUNTS" in SAFETY_CRITICAL_KEYS
    assert "YUGEN_MT5_REAL_ACCOUNT_CONSENT" in SAFETY_CRITICAL_KEYS
    assert len(SAFETY_CRITICAL_KEYS) == 3
