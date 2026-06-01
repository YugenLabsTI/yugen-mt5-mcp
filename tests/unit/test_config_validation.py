from __future__ import annotations

import pytest

from yugen_mt5_mcp.config import AppConfig, ConfigError, TransportMode


def test_default_config_is_stdio_and_safe() -> None:
    config = AppConfig()

    config.validate_startup()

    assert config.transport.mode is TransportMode.STDIO
    assert config.transport.remote.enabled is False
    assert config.transport.remote.host == "127.0.0.1"
    assert config.transport.remote.allowlist == ("127.0.0.1/32", "::1/128")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {
                "transport": {
                    "mode": "remote",
                    "remote": {"enabled": True, "bearer_token": "secret-token"},
                }
            },
            "TLS termination",
        ),
        (
            {
                "transport": {
                    "mode": "remote",
                    "remote": {"enabled": True, "tls_terminated": True},
                }
            },
            "bearer token",
        ),
        (
            {
                "transport": {
                    "mode": "remote",
                    "remote": {
                        "enabled": True,
                        "host": "0.0.0.0",
                        "tls_terminated": True,
                        "bearer_token": "secret-token",
                    },
                }
            },
            "wildcard bind",
        ),
    ],
)
def test_remote_mode_rejects_unsafe_settings(payload: dict[str, object], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        AppConfig.from_mapping(payload)


def test_stdio_mode_rejects_enabled_remote_transport() -> None:
    with pytest.raises(ConfigError, match="must stay disabled"):
        AppConfig.from_mapping(
            {
                "transport": {
                    "mode": "stdio",
                    "remote": {
                        "enabled": True,
                        "host": "127.0.0.1",
                    },
                }
            }
        )


def test_remote_mode_accepts_explicit_safe_configuration() -> None:
    config = AppConfig.from_mapping(
        {
            "transport": {
                "mode": "remote",
                "remote": {
                    "enabled": True,
                    "host": "127.0.0.1",
                    "port": 9443,
                    "tls_terminated": True,
                    "bearer_token": "secret-token",
                    "allowlist": ["127.0.0.1/32", "10.0.0.0/24"],
                },
            },
            "audit": {"database_path": "var/custom.sqlite3"},
            "risk": {"allowed_symbols": ["EURUSD", "XAUUSD"]},
        }
    )

    assert config.transport.mode is TransportMode.REMOTE
    assert config.transport.remote.port == 9443
    assert config.audit.database_path.as_posix() == "var/custom.sqlite3"
    assert config.risk.allowed_symbols == ("EURUSD", "XAUUSD")
