"""Config provenance tracking — leaf module.

Provides ``ConfigSource`` (StrEnum) and ``derive_provenance`` helper for
computing the origin of each safety-critical config key.  This module has no
heavy imports so cli.py, app.py, and doctor.py can all import it without
pulling in the full application graph.

Provenance is SIDECAR metadata — it never flows into gate decision logic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum


class ConfigSource(StrEnum):
    """Origin of a resolved configuration value."""

    OS_ENVIRON = "os.environ"
    ENV_FILE = "env-file"
    DEFAULT = "default"


# The three env keys that gate safety-critical trading operations.
SAFETY_CRITICAL_KEYS: tuple[str, ...] = (
    "YUGEN_MT5_ALLOW_LIVE_TRADING",
    "YUGEN_MT5_ALLOW_REAL_ACCOUNTS",
    "YUGEN_MT5_REAL_ACCOUNT_CONSENT",
)


def derive_provenance(
    file_values: Mapping[str, str],
    os_environ: Mapping[str, str],
    tracked_keys: Sequence[str],
) -> dict[str, ConfigSource]:
    """Return a ``{key: source}`` map for each key in *tracked_keys*.

    Resolution order (highest priority first):
    1. ``os_environ`` → ``ConfigSource.OS_ENVIRON``
    2. ``file_values`` → ``ConfigSource.ENV_FILE``
    3. absent from both → ``ConfigSource.DEFAULT``

    The merged dict is NOT recomputed here — that is the caller's
    responsibility.  Provenance is derived from the two source dicts
    independently so the merge byte-stays identical.
    """
    result: dict[str, ConfigSource] = {}
    for key in tracked_keys:
        if key in os_environ:
            result[key] = ConfigSource.OS_ENVIRON
        elif key in file_values:
            result[key] = ConfigSource.ENV_FILE
        else:
            result[key] = ConfigSource.DEFAULT
    return result
