from __future__ import annotations

from yugen_mt5_mcp.session import SessionRiskStore


def test_acknowledgement_is_scoped_to_current_store_instance() -> None:
    current_session = SessionRiskStore()
    current_session.acknowledge_real_account(
        session_id="session-1",
        actor="agent:test",
        account_login=123456,
    )

    assert (
        current_session.has_real_account_ack(session_id="session-1", account_login=123456) is True
    )
    assert SessionRiskStore().has_real_account_ack(
        session_id="session-1",
        account_login=123456,
    ) is False


def test_clear_session_removes_acknowledgements() -> None:
    store = SessionRiskStore()
    store.acknowledge_real_account(session_id="session-1", actor="agent:test", account_login=1)
    store.acknowledge_real_account(session_id="session-2", actor="agent:test", account_login=2)

    store.clear_session("session-1")

    assert store.has_real_account_ack(session_id="session-1", account_login=1) is False
    assert store.has_real_account_ack(session_id="session-2", account_login=2) is True
