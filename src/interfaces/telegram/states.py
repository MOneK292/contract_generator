"""Telegram finite-state machine and user session models."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from aiogram.fsm.state import State, StatesGroup

_SESSION_TTL_SECONDS: int = 30 * 60  # 30 minutes
_EVICTION_CHECK_INTERVAL: int = 60  # run eviction at most once per 60 seconds


class ContractFlow(StatesGroup):
    """FSM states for the contract selection flow."""

    waiting_project = State()
    waiting_vacancy = State()
    waiting_template = State()
    waiting_employee_data = State()
    waiting_missing_fields = State()


@dataclass
class UserSession:
    """Selected values for a Telegram user."""

    project: str | None = None
    vacancy: str | None = None
    template: str | None = None
    employee_text: str = ""
    missing_fields: list[str] = field(default_factory=list)
    pending_request: Any | None = None
    last_activity: float = field(default_factory=time.monotonic)

    def touch(self) -> None:
        """Update activity timestamp."""
        self.last_activity = time.monotonic()

    def clear_pending_generation(self) -> None:
        """Clear accumulated employee data used by the missing-fields wizard."""
        self.employee_text = ""
        self.missing_fields.clear()
        self.pending_request = None


@dataclass
class UserSessionStore:
    """In-memory storage for user sessions with TTL-based eviction."""

    _sessions: dict[int, UserSession] = field(default_factory=dict)
    _last_eviction: float = field(default_factory=time.monotonic)

    def get(self, user_id: int) -> UserSession:
        """Return a user session, creating it when necessary."""
        self._maybe_evict()
        session = self._sessions.setdefault(user_id, UserSession())
        session.touch()
        return session

    def reset(self, user_id: int) -> UserSession:
        """Reset and return a user session."""
        self._maybe_evict()
        session = UserSession()
        self._sessions[user_id] = session
        return session

    def _maybe_evict(self) -> None:
        """Remove sessions idle for longer than TTL (runs at most once per interval)."""
        now = time.monotonic()
        if now - self._last_eviction < _EVICTION_CHECK_INTERVAL:
            return
        self._last_eviction = now
        cutoff = now - _SESSION_TTL_SECONDS
        expired = [uid for uid, s in self._sessions.items() if s.last_activity < cutoff]
        for uid in expired:
            del self._sessions[uid]

