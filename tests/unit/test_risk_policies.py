from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tests.fakes.fake_mt5 import FakeMT5Backend
from yugen_mt5_mcp.audit import AuditStore
from yugen_mt5_mcp.config import AppConfig, RiskConfig
from yugen_mt5_mcp.mt5_adapter import MT5Adapter
from yugen_mt5_mcp.risk import RiskCheckRequest, RiskPolicy, RiskPolicyError, TradeAction
from yugen_mt5_mcp.session import SessionRiskStore


def build_policy(
    tmp_path: Path,
    *,
    risk_config: RiskConfig,
    backend: FakeMT5Backend | None = None,
    now: datetime | None = None,
) -> tuple[RiskPolicy, MT5Adapter, SessionRiskStore, AuditStore]:
    audit_store = AuditStore(tmp_path / "audit.sqlite3")
    session_store = SessionRiskStore()
    adapter = MT5Adapter(backend=backend or FakeMT5Backend())
    policy = RiskPolicy(
        config=AppConfig(risk=risk_config),
        session_store=session_store,
        audit_store=audit_store,
        clock=(lambda: now) if now is not None else None,
    )
    return policy, adapter, session_store, audit_store


def test_real_account_requires_current_session_acknowledgement(tmp_path: Path) -> None:
    backend = FakeMT5Backend()
    backend.account.trade_mode = backend.ACCOUNT_TRADE_MODE_REAL
    policy, adapter, _, audit_store = build_policy(
        tmp_path,
        risk_config=RiskConfig(
            allowed_symbols=("EURUSD",),
            allowed_account_modes=("hedging",),
            allow_live_trading=True,
            allow_real_accounts=True,
        ),
        backend=backend,
    )

    with pytest.raises(RiskPolicyError, match="acknowledgement"):
        policy.validate(
            RiskCheckRequest(
                session_id="session-1",
                actor="agent:test",
                action=TradeAction.OPEN,
                symbol="EURUSD",
                volume=Decimal("0.10"),
                account=adapter.get_account(),
                positions=adapter.list_positions("EURUSD"),
            )
        )

    rows = audit_store.fetch_all()
    payload = json.loads(rows[-1]["context_json"])
    assert rows[-1]["decision"] == "rejected"
    assert payload["trade_mode"] == "real"


def test_real_account_is_allowed_after_acknowledgement(tmp_path: Path) -> None:
    backend = FakeMT5Backend()
    backend.account.trade_mode = backend.ACCOUNT_TRADE_MODE_REAL
    policy, adapter, session_store, _ = build_policy(
        tmp_path,
        risk_config=RiskConfig(
            allowed_symbols=("EURUSD",),
            allowed_account_modes=("hedging",),
            allow_live_trading=True,
            allow_real_accounts=True,
        ),
        backend=backend,
    )
    account = adapter.get_account()
    session_store.acknowledge_real_account(
        session_id="session-1",
        actor="agent:test",
        account_login=account.login,
    )

    approval = policy.validate(
        RiskCheckRequest(
            session_id="session-1",
            actor="agent:test",
            action=TradeAction.CLOSE,
            symbol="EURUSD",
            volume=Decimal("0.10"),
            account=account,
            positions=adapter.list_positions("EURUSD"),
        )
    )

    assert approval.action is TradeAction.CLOSE
    assert approval.account_login == account.login


def test_risk_policy_blocks_outside_trading_window(tmp_path: Path) -> None:
    policy, adapter, _, _ = build_policy(
        tmp_path,
        risk_config=RiskConfig(
            allowed_symbols=("EURUSD",),
            allowed_account_modes=("hedging",),
            allow_live_trading=True,
            trading_window_start=datetime(2024, 1, 1, 9, 0, tzinfo=UTC).time(),
            trading_window_end=datetime(2024, 1, 1, 17, 0, tzinfo=UTC).time(),
        ),
        now=datetime(2024, 1, 1, 20, 0, tzinfo=UTC),
    )

    with pytest.raises(RiskPolicyError, match="outside the configured trading window"):
        policy.validate(
            RiskCheckRequest(
                session_id="session-1",
                actor="agent:test",
                action=TradeAction.OPEN,
                symbol="EURUSD",
                volume=Decimal("0.10"),
                account=adapter.get_account(),
                positions=adapter.list_positions("EURUSD"),
            )
        )


def test_risk_policy_blocks_excess_exposure(tmp_path: Path) -> None:
    policy, adapter, _, _ = build_policy(
        tmp_path,
        risk_config=RiskConfig(
            allowed_symbols=("EURUSD",),
            allowed_account_modes=("hedging",),
            allow_live_trading=True,
            max_order_volume=Decimal("1.00"),
            max_symbol_exposure=Decimal("0.25"),
        ),
    )

    with pytest.raises(RiskPolicyError, match="max_symbol_exposure"):
        policy.validate(
            RiskCheckRequest(
                session_id="session-1",
                actor="agent:test",
                action=TradeAction.OPEN,
                symbol="EURUSD",
                volume=Decimal("0.10"),
                account=adapter.get_account(),
                positions=adapter.list_positions("EURUSD"),
            )
        )


def test_wildcard_allowed_symbols_permits_any_symbol_for_trading(
    tmp_path: Path,
) -> None:
    policy, adapter, _, _ = build_policy(
        tmp_path,
        risk_config=RiskConfig(
            allowed_symbols=("*",),
            allowed_account_modes=("hedging",),
            allow_live_trading=True,
        ),
    )

    approval = policy.validate(
        RiskCheckRequest(
            session_id="session-1",
            actor="agent:test",
            action=TradeAction.OPEN,
            symbol="Boom 1000 Index",
            volume=Decimal("0.10"),
            account=adapter.get_account(),
            positions=adapter.list_positions("EURUSD"),
        )
    )

    assert approval.symbol == "Boom 1000 Index"


def test_wildcard_allowed_symbols_does_not_relax_live_trading_gate(
    tmp_path: Path,
) -> None:
    policy, adapter, _, _ = build_policy(
        tmp_path,
        risk_config=RiskConfig(
            allowed_symbols=("*",),
            allowed_account_modes=("hedging",),
            allow_live_trading=False,
        ),
    )

    with pytest.raises(RiskPolicyError, match="live trading is disabled"):
        policy.validate(
            RiskCheckRequest(
                session_id="session-1",
                actor="agent:test",
                action=TradeAction.OPEN,
                symbol="Boom 1000 Index",
                volume=Decimal("0.10"),
                account=adapter.get_account(),
                positions=adapter.list_positions("EURUSD"),
            )
        )
