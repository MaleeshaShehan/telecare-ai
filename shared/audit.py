"""Audit log: one row per agent decision in data/db/audit.db.

Stores the decision and the reason, never the raw message text. This is our
accountability evidence and feeds the UI's agent-trace panel.

Usage:
    from shared.audit import log_decision
    log_decision(conversation_id, "orchestrator", "route->account_agent", "intent=bill_enquiry")
"""
import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from shared.config import settings

AUDIT_DB = Path("data/db/audit.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    agent           TEXT NOT NULL,
    decision        TEXT NOT NULL,
    reason          TEXT NOT NULL
);
"""

_configured_audit_key = settings.jwt_secret.strip().encode("utf-8")
_AUDIT_KEY = _configured_audit_key if len(_configured_audit_key) >= 32 else secrets.token_bytes(32)


def _audit_id(conversation_id: str) -> str:
    """Return a keyed, non-PII identifier suitable for persistent logs."""
    digest = hmac.new(
        _AUDIT_KEY,
        str(conversation_id).encode("utf-8", errors="replace"),
        hashlib.sha256,
    ).hexdigest()
    return f"h1:{digest}"


def _connect() -> sqlite3.Connection:
    AUDIT_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute(_SCHEMA)
    # Migrate any legacy plaintext/client-controlled identifiers in place.
    legacy_rows = conn.execute(
        "SELECT id, conversation_id FROM audit WHERE conversation_id NOT LIKE 'h1:%'"
    ).fetchall()
    if legacy_rows:
        conn.executemany(
            "UPDATE audit SET conversation_id = ? WHERE id = ?",
            [(_audit_id(value), row_id) for row_id, value in legacy_rows],
        )
    return conn


def log_decision(conversation_id: str, agent: str, decision: str, reason: str) -> None:
    """Append one decision row. Parameterised SQL only."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO audit (ts, conversation_id, agent, decision, reason) VALUES (?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), _audit_id(conversation_id), agent, decision, reason),
        )


def get_trace(conversation_id: str) -> list[dict]:
    """All decisions for one conversation, oldest first. Used by the trace panel."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ts, agent, decision, reason FROM audit WHERE conversation_id = ? ORDER BY id",
            (_audit_id(conversation_id),),
        ).fetchall()
    return [dict(r) for r in rows]


def rekey_trace(old_conversation_id: str, new_conversation_id: str) -> None:
    """Move audit history when an authenticated session identifier rotates."""
    with _connect() as conn:
        conn.execute(
            "UPDATE audit SET conversation_id = ? WHERE conversation_id = ?",
            (_audit_id(new_conversation_id), _audit_id(old_conversation_id)),
        )
