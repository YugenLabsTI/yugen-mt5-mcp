from __future__ import annotations

from decimal import Decimal

import pytest

from yugen_mt5_mcp.mt5_adapter import AccountMode, AccountSnapshot, AccountTradeMode
from yugen_mt5_mcp.security import DemoSmokeControls, RemoteSecurityError


def test_demo_smoke_controls_stay_disabled_without_opt_in() -> None:
    controls = DemoSmokeControls.from_env({})

    assert controls.enabled is False
    assert controls.max_volume == Decimal("0.01")
    assert controls.allowed_symbols == ("EURUSD",)


def test_demo_smoke_opt_in_requires_demo_only_acknowledgement() -> None:
    with pytest.raises(RemoteSecurityError, match="demo-only"):
        DemoSmokeControls.from_env({"YUGEN_MT5_ENABLE_DEMO_SMOKE": "1"})


def test_demo_smoke_guardrails_reject_real_accounts_and_oversized_orders() -> None:
    controls = DemoSmokeControls.from_env(
        {
            "YUGEN_MT5_ENABLE_DEMO_SMOKE": "1",
            "YUGEN_MT5_DEMO_SMOKE_ACK": "demo-only",
            "YUGEN_MT5_DEMO_SMOKE_SYMBOLS": "EURUSD, XAUUSD",
            "YUGEN_MT5_DEMO_SMOKE_MAX_VOLUME": "0.01",
        }
    )

    with pytest.raises(RemoteSecurityError, match="real accounts"):
        controls.validate_account(
            AccountSnapshot(
                login=2001,
                server="Real-Server",
                balance=1000.0,
                equity=1000.0,
                margin_free=1000.0,
                leverage=100,
                currency="USD",
                company="Yugen",
                account_mode=AccountMode.HEDGING,
                trade_mode=AccountTradeMode.REAL,
            )
        )

    controls.validate_account(
        AccountSnapshot(
            login=1001,
            server="Demo-Server",
            balance=1000.0,
            equity=1000.0,
            margin_free=1000.0,
            leverage=100,
            currency="USD",
            company="Yugen",
            account_mode=AccountMode.HEDGING,
            trade_mode=AccountTradeMode.DEMO,
        )
    )

    assert controls.validate_request(symbol="eurusd", volume=Decimal("0.01")) == "EURUSD"

    with pytest.raises(RemoteSecurityError, match="not in the demo smoke allowlist"):
        controls.validate_request(symbol="GBPUSD", volume=Decimal("0.01"))

    with pytest.raises(RemoteSecurityError, match="max volume"):
        controls.validate_request(symbol="EURUSD", volume=Decimal("0.02"))
