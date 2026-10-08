"""Ticket store in data/db/tickets.db.   Owner: M4

    create_ticket(conversation_id, summary: dict, priority) -> str   # "T-1001", "T-1002", ...
    list_open_tickets() -> list[dict]                                 # for ui/pages/console.py

Parameterised SQL only.
"""

import sqlite3
import os
from datetime import datetime, timezone
import uuid

DB_PATH = "data/db/tickets.db"

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT UNIQUE,
                created_at TEXT,
                priority TEXT,
                status TEXT DEFAULT 'open',
                issue TEXT,
                customer_mood TEXT,
                conversation_id TEXT
            )
        """)

def create_ticket(conversation_id: str, summary: dict, priority: str) -> str:
    init_db()
    with get_db() as conn:
        # Read the numeric part of the last ticket_id (e.g. "T-1001" -> 1001)
        # Use CAST + SUBSTR so it works whether the table is empty or not.
        cursor = conn.execute(
            "SELECT MAX(CAST(SUBSTR(ticket_id, 3) AS INTEGER)) FROM tickets"
        )
        last_num = cursor.fetchone()[0] or 1000
        ticket_id = f"T-{last_num + 1}"

        created_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO tickets (ticket_id, created_at, priority, issue, customer_mood, conversation_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                ticket_id,
                created_at,
                priority,
                summary.get("issue", "No issue provided"),
                summary.get("customer_mood", "unknown"),
                conversation_id,
            ),
        )
        conn.commit()
        return ticket_id

def list_open_tickets() -> list[dict]:
    init_db()
    with get_db() as conn:
        cursor = conn.execute("SELECT * FROM tickets WHERE status = 'open' ORDER BY id DESC")
        return [dict(row) for row in cursor.fetchall()]