"""Tests for RemoteTransportConfig new fields: allow_insecure, stateless_http, path."""

from __future__ import annotations

from yugen_mt5_mcp.config import AppConfig, RemoteTransportConfig


class TestRemoteTransportConfigDefaults:
    def test_allow_insecure_defaults_to_false(self) -> None:
        cfg = RemoteTransportConfig()
        assert cfg.allow_insecure is False

    def test_stateless_http_defaults_to_false(self) -> None:
        cfg = RemoteTransportConfig()
        assert cfg.stateless_http is False

    def test_path_defaults_to_slash_mcp_slash(self) -> None:
        cfg = RemoteTransportConfig()
        assert cfg.path == "/mcp/"

    def test_allowlist_default_is_loopback_only(self) -> None:
        cfg = RemoteTransportConfig()
        assert cfg.allowlist == ("127.0.0.1/32", "::1/128")


class TestRemoteTransportConfigFromMapping:
    """from_mapping should deserialise the three new fields."""

    def _remote_mapping(self, **overrides: object) -> dict[str, object]:
        """Return a minimal valid remote payload dict."""
        base: dict[str, object] = {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 9443,
            "bearer_token": "tok",
            "tls_terminated": False,
            "allowlist": ["127.0.0.1/32"],
        }
        base.update(overrides)
        return base

    def _build_config(self, **remote_overrides: object) -> AppConfig:
        return AppConfig.from_mapping(
            {
                "transport": {
                    "mode": "remote",
                    "remote": self._remote_mapping(**remote_overrides),
                }
            }
        )

    def test_allow_insecure_true_deserialised(self) -> None:
        cfg = self._build_config(allow_insecure=True)
        assert cfg.transport.remote.allow_insecure is True

    def test_allow_insecure_false_deserialised(self) -> None:
        cfg = self._build_config(allow_insecure=False)
        assert cfg.transport.remote.allow_insecure is False

    def test_stateless_http_true_deserialised(self) -> None:
        cfg = self._build_config(stateless_http=True)
        assert cfg.transport.remote.stateless_http is True

    def test_stateless_http_false_deserialised(self) -> None:
        cfg = self._build_config(stateless_http=False)
        assert cfg.transport.remote.stateless_http is False

    def test_path_custom_deserialised(self) -> None:
        cfg = self._build_config(path="/api/mcp/")
        assert cfg.transport.remote.path == "/api/mcp/"

    def test_path_default_when_absent(self) -> None:
        cfg = self._build_config()
        assert cfg.transport.remote.path == "/mcp/"
