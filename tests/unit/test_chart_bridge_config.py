"""Unit tests for ChartBridgeConfig after the pipe_name swap (A-4).

Replaces the old loopback-IP / port validation tests with pipe-name validation.
"""

from __future__ import annotations

import pytest

from yugen_mt5_mcp.chart_bridge import ChartBridgeConfig


class TestChartBridgeConfigValidation:
    def test_valid_default_config_passes(self) -> None:
        """A config with only shared_secret set must pass validation."""
        config = ChartBridgeConfig(shared_secret="s3cr3t")
        config.validate()  # must not raise

    def test_valid_custom_pipe_name_passes(self) -> None:
        """A bare pipe name (no path separators) must be accepted."""
        config = ChartBridgeConfig(pipe_name="my_custom_bridge", shared_secret="s3cr3t")
        config.validate()

    def test_empty_pipe_name_is_rejected(self) -> None:
        """An empty pipe_name must raise ValueError."""
        config = ChartBridgeConfig(pipe_name="", shared_secret="s3cr3t")
        with pytest.raises(ValueError, match="pipe_name"):
            config.validate()

    def test_pipe_name_with_backslash_is_rejected(self) -> None:
        """A pipe_name containing a backslash must raise ValueError.

        The name must be a bare identifier — the transport prepends the UNC path.
        """
        config = ChartBridgeConfig(pipe_name="\\\\.\\ pipe\\bad", shared_secret="s3cr3t")
        with pytest.raises(ValueError, match="pipe_name"):
            config.validate()

    def test_pipe_name_with_forward_slash_is_rejected(self) -> None:
        """A pipe_name containing a forward slash must raise ValueError."""
        config = ChartBridgeConfig(pipe_name="my/bridge", shared_secret="s3cr3t")
        with pytest.raises(ValueError, match="pipe_name"):
            config.validate()

    def test_empty_shared_secret_is_rejected(self) -> None:
        """An empty shared_secret must raise ValueError."""
        config = ChartBridgeConfig(shared_secret="")
        with pytest.raises(ValueError, match="shared_secret"):
            config.validate()

    def test_blank_shared_secret_is_rejected(self) -> None:
        """A whitespace-only shared_secret must raise ValueError."""
        config = ChartBridgeConfig(shared_secret="   ")
        with pytest.raises(ValueError, match="shared_secret"):
            config.validate()

    def test_non_positive_timeout_is_rejected(self) -> None:
        """A timeout_seconds <= 0 must raise ValueError."""
        config = ChartBridgeConfig(shared_secret="s3cr3t", timeout_seconds=0.0)
        with pytest.raises(ValueError, match="timeout"):
            config.validate()

    def test_negative_timeout_is_rejected(self) -> None:
        """A negative timeout_seconds must raise ValueError."""
        config = ChartBridgeConfig(shared_secret="s3cr3t", timeout_seconds=-1.0)
        with pytest.raises(ValueError, match="timeout"):
            config.validate()

    def test_config_has_no_host_or_port_fields(self) -> None:
        """ChartBridgeConfig must not have host or port fields."""
        config = ChartBridgeConfig(shared_secret="s3cr3t")
        assert not hasattr(config, "host")
        assert not hasattr(config, "port")

    def test_default_pipe_name_is_yugen_chart_bridge(self) -> None:
        """Default pipe_name must be 'yugen_chart_bridge'."""
        config = ChartBridgeConfig(shared_secret="s3cr3t")
        assert config.pipe_name == "yugen_chart_bridge"
