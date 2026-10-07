"""Audit log: one row per agent decision in data/db/audit.db.

Stores the decision and the reason, never the raw message text. This is our
accountability evidence and feeds the UI's agent-trace panel.

Usage:
    from shared.audit import log_decision
    log_decision(conversation_id, "orchestrator", "route->account_agent", "intent=bill_enquiry")
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

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


def _connect() -> sqlite3.Connection:
    AUDIT_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute(_SCHEMA)
    return conn


def log_decision(conversation_id: str, agent: str, decision: str, reason: str) -> None:
    """Append one decision row. Parameterised SQL only."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO audit (ts, conversation_id, agent, decision, reason) VALUES (?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), conversation_id, agent, decision, reason),
        )


def get_trace(conversation_id: str) -> list[dict]:
    """All decisions for one conversation, oldest first. Used by the trace panel."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ts, agent, decision, reason FROM audit WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
    return [dict(r) for r in rows]
