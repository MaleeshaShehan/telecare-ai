"""Conversation state, in memory, keyed by conversation_id.   Owner: M1

Holds: current JWT, last 10 turns, failed-answer counter, whether the AI
disclosure has been shown. In-memory is fine for the demo; the report says
production would use Redis. The JWT never leaves this process: the browser
only ever learns "logged in" or "not logged in".
"""
from collections import defaultdict

MAX_TURNS = 10


def _new() -> dict:
    return {"token": None, "history": [], "failed_count": 0, "disclosed": False}


_SESSIONS: dict[str, dict] = defaultdict(_new)


def get(conversation_id: str) -> dict:
    return _SESSIONS[conversation_id]


def get_token(conversation_id: str) -> str | None:
    return _SESSIONS[conversation_id]["token"]


def set_token(conversation_id: str, token: str | None) -> None:
    _SESSIONS[conversation_id]["token"] = token


def add_turn(conversation_id: str, role: str, text: str) -> None:
    history = _SESSIONS[conversation_id]["history"]
    history.append({"role": role, "text": text})
    del history[:-MAX_TURNS]  # keep the last 10 turns only


def record_outcome(conversation_id: str, status: str) -> int:
    """Count consecutive failed answers; the Supervisor escalates at two."""
    state = _SESSIONS[conversation_id]
    if status in ("not_found", "error"):
        state["failed_count"] += 1
    elif status == "ok":
        state["failed_count"] = 0
    return state["failed_count"]


def reset(conversation_id: str) -> None:
    _SESSIONS.pop(conversation_id, None)
