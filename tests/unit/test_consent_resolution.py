"""WU7 — 3-source real-account consent resolution tests (TDD: RED first)."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from tests.fakes.fake_mt5 import FakeMT5Backend
from yugen_mt5_mcp.audit import AuditStore
from yugen_mt5_mcp.config import AppConfig, RiskConfig
from yugen_mt5_mcp.mt5_adapter import MT5Adapter
from yugen_mt5_mcp.risk import RiskCheckRequest, RiskPolicy, RiskPolicyError, TradeAction
from yugen_mt5_mcp.session import SessionRiskStore


def _make_real_backend() -> FakeMT5Backend:
    backend = FakeMT5Backend()
    backend.account.trade_mode = backend.ACCOUNT_TRADE_MODE_REAL
    return backend


def _build_policy(
    tmp_path: Path,
    *,
    risk_config: RiskConfig,
    backend: FakeMT5Backend | None = None,
) -> tuple[RiskPolicy, MT5Adapter, SessionRiskStore, AuditStore]:
    audit_store = AuditStore(tmp_path / "audit.sqlite3")
    session_store = SessionRiskStore()
    adapter = MT5Adapter(backend=backend or FakeMT5Backend())
    policy = RiskPolicy(
        config=AppConfig(risk=risk_config),
        session_store=session_store,
        audit_store=audit_store,
    )
    return policy, adapter, session_store, audit_store


# ---------------------------------------------------------------------------
# WU7-T1: explicit actor wins over config default and env-var (CD-1-a)
# Explicit session ack with explicit actor ID is the highest-priority source.
# ---------------------------------------------------------------------------


def test_explicit_session_ack_wins_over_env_var_and_config(tmp_path: Path) -> None:
    backend = _make_real_backend()
    policy, adapter, session_store, _ = _build_policy(
        tmp_path,
        risk_config=RiskConfig(
            allowed_symbols=("EURUSD",),
            allowed_account_modes=("hedging",),
            allow_live_trading=True,
            allow_real_accounts=True,
            real_account_consent_env=True,  # env-var path also active
            default_actor="config-default-actor",
        ),
        backend=backend,
    )
    account = adapter.get_account()
    # Explicit per-session ack with a specific actor
    session_store.acknowledge_real_account(
        session_id="session-explicit",
        actor="explicit@example.com",
        account_login=account.login,
    )

    # Should succeed — explicit ack present
    approval = policy.validate(
        RiskCheckRequest(
            session_id="session-explicit",
            actor="explicit@example.com",
            action=TradeAction.OPEN,
            symbol="EURUSD",
            volume=Decimal("0.10"),
            account=account,
            positions=adapter.list_positions("EURUSD"),
        )
    )
    assert approval.action is TradeAction.OPEN


# ---------------------------------------------------------------------------
# WU7-T2: env var truthy + no explicit session ack → ack succeeds (CD-1-b)
# When real_account_consent_env=True, per-session ack is NOT required.
# ---------------------------------------------------------------------------


def test_env_var_consent_bypasses_per_session_ack(tmp_path: Path) -> None:
    backend = _make_real_backend()
    policy, adapter, session_store, _ = _build_policy(
        tmp_path,
        risk_config=RiskConfig(
            allowed_symbols=("EURUSD",),
            allowed_account_modes=("hedging",),
            allow_live_trading=True,
            allow_real_accounts=True,
            real_account_consent_env=True,
        ),
        backend=backend,
    )
    account = adapter.get_account()
    # No explicit session ack stored

    # Should succeed because env-var consent is active
    approval = policy.validate(
        RiskCheckRequest(
            session_id="session-no-ack",
            actor="mcp.trade",
            action=TradeAction.OPEN,
            symbol="EURUSD",
            volume=Decimal("0.10"),
            account=account,
            positions=adapter.list_positions("EURUSD"),
        )
    )
    assert approval.action is TradeAction.OPEN


# ---------------------------------------------------------------------------
# WU7-T3: config default actor used when no explicit actor and env-var off
# (AT-7-b) — per-session ack stored with the default actor satisfies check.
# ---------------------------------------------------------------------------


def test_config_default_actor_satisfies_ack_when_env_off(tmp_path: Path) -> None:
    backend = _make_real_backend()
    policy, adapter, session_store, _ = _build_policy(
        tmp_path,
        risk_config=RiskConfig(
            allowed_symbols=("EURUSD",),
            allowed_account_modes=("hedging",),
            allow_live_trading=True,
            allow_real_accounts=True,
            real_account_consent_env=False,  # env-var off
            default_actor="mcp.trade",
        ),
        backend=backend,
    )
    account = adapter.get_account()
    # Ack stored using default actor
    session_store.acknowledge_real_account(
        session_id="session-default-actor",
        actor="mcp.trade",
        account_login=account.login,
    )

    approval = policy.validate(
        RiskCheckRequest(
            session_id="session-default-actor",
            actor="mcp.trade",
            action=TradeAction.OPEN,
            symbol="EURUSD",
            volume=Decimal("0.10"),
            account=account,
            positions=adapter.list_positions("EURUSD"),
        )
    )
    assert approval.action is TradeAction.OPEN


# ---------------------------------------------------------------------------
# WU7-T4: fresh session after restart → rejected with re-acknowledgement msg
# (AT-7-c) — env-var off, no ack → must reject.
# ---------------------------------------------------------------------------


def test_trading_rejected_without_session_ack_when_env_off(tmp_path: Path) -> None:
    backend = _make_real_backend()
    policy, adapter, _, _ = _build_policy(
        tmp_path,
        risk_config=RiskConfig(
            allowed_symbols=("EURUSD",),
            allowed_account_modes=("hedging",),
            allow_live_trading=True,
            allow_real_accounts=True,
            real_account_consent_env=False,  # env-var off
        ),
        backend=backend,
    )
    account = adapter.get_account()
    # Fresh session store — no ack present

    with pytest.raises(RiskPolicyError, match="acknowledgement"):
        policy.validate(
            RiskCheckRequest(
                session_id="fresh-session",
                actor="mcp.trade",
                action=TradeAction.OPEN,
                symbol="EURUSD",
                volume=Decimal("0.10"),
                account=account,
                positions=adapter.list_positions("EURUSD"),
            )
        )
