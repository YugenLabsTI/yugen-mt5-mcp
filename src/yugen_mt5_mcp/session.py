"""In-memory session state for real-account risk acknowledgements."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(slots=True, frozen=True)
class RiskAcknowledgement:
    session_id: str
    actor: str
    account_login: int
    acknowledged_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class SessionRiskStore:
    def __init__(self) -> None:
        self._acks: dict[tuple[str, int], RiskAcknowledgement] = {}

    def acknowledge_real_account(
        self,
        *,
        session_id: str,
        actor: str,
        account_login: int,
    ) -> RiskAcknowledgement:
        acknowledgement = RiskAcknowledgement(
            session_id=session_id,
            actor=actor,
            account_login=account_login,
        )
        self._acks[(session_id, account_login)] = acknowledgement
        return acknowledgement

    def has_real_account_ack(self, *, session_id: str, account_login: int) -> bool:
        return (session_id, account_login) in self._acks

    def clear_session(self, session_id: str) -> None:
        keys = [key for key in self._acks if key[0] == session_id]
        for key in keys:
            del self._acks[key]
