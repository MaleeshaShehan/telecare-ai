"""Server-issued, expiring Orchestrator sessions.

The browser receives only a random HttpOnly cookie. JWTs and conversation
state remain server-side and are never selected by a request body or query
parameter. Production deployments should replace this process-local store
with Redis while preserving the same interface.
"""
from __future__ import annotations

import secrets
from time import monotonic


COOKIE_NAME = "telecare_session"
MAX_TURNS = 10
IDLE_TTL_SECONDS = 15 * 60
ABSOLUTE_TTL_SECONDS = 60 * 60


def _new(now: float | None = None) -> dict:
    timestamp = monotonic() if now is None else now
    return {
        "token": None,
        "history": [],
        "failed_count": 0,
        "disclosed": False,
        "created_at": timestamp,
        "last_seen": timestamp,
    }


_SESSIONS: dict[str, dict] = {}


def _active(session_id: str | None, *, touch: bool = True) -> dict | None:
    if not session_id:
        return None
    state = _SESSIONS.get(session_id)
    if state is None:
        return None
    now = monotonic()
    if (
        now - state["last_seen"] > IDLE_TTL_SECONDS
        or now - state["created_at"] > ABSOLUTE_TTL_SECONDS
    ):
        _SESSIONS.pop(session_id, None)
        return None
    if touch:
        state["last_seen"] = now
    return state


def create() -> str:
    while True:
        session_id = secrets.token_urlsafe(32)
        if session_id not in _SESSIONS:
            _SESSIONS[session_id] = _new()
            return session_id


def resolve(cookie_value: str | None) -> tuple[str, bool]:
    """Resolve a valid server-issued cookie or create a fresh anonymous session."""
    if _active(cookie_value) is not None:
        return str(cookie_value), False
    return create(), True


def rotate(session_id: str) -> str:
    """Rotate after authentication to prevent session fixation."""
    old = _active(session_id, touch=False) or _new()
    new_id = create()
    now = monotonic()
    old["created_at"] = now
    old["last_seen"] = now
    _SESSIONS[new_id] = old
    _SESSIONS.pop(session_id, None)
    return new_id


def get(session_id: str) -> dict:
    """Internal access for a session already resolved by the HTTP boundary."""
    state = _active(session_id)
    if state is None:
        state = _new()
        _SESSIONS[session_id] = state
    return state


def get_token(session_id: str) -> str | None:
    state = _active(session_id)
    return state["token"] if state else None


def set_token(session_id: str, token: str | None) -> None:
    get(session_id)["token"] = token


def add_turn(session_id: str, role: str, text: str) -> None:
    history = get(session_id)["history"]
    history.append({"role": role, "text": text})
    del history[:-MAX_TURNS]


def record_outcome(session_id: str, status: str) -> int:
    """Count consecutive failed answers; the Supervisor escalates at two."""
    state = get(session_id)
    if status in ("not_found", "error"):
        state["failed_count"] += 1
    elif status == "ok":
        state["failed_count"] = 0
    return state["failed_count"]


def reset(session_id: str) -> None:
    _SESSIONS.pop(session_id, None)


def clear_all() -> None:
    """Test helper: remove every process-local session."""
    _SESSIONS.clear()
