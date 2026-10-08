"""Ticket store. Uses Supabase if credentials are provided, else SQLite.   Owner: M4

    create_ticket(conversation_id, summary: dict, priority) -> str
    list_open_tickets() -> list[dict]

Features:
    - Dual backend: Supabase Postgres (cloud) or SQLite (local, offline tests).
    - Round-robin assignment to one of the 4 registered human agents.
    - Email notification to the assigned human agent (mock-logs if SMTP not set).

Dual-backend rule:
    If SUPABASE_URL + SUPABASE_KEY are set in .env -> Supabase.
    Otherwise -> SQLite fallback (used for pytest and offline development).
"""
import os
import sqlite3
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

# --- Supabase credentials (read directly to avoid editing shared/config.py) ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

try:
    from supabase import create_client, Client
    SUPABASE_LIB_AVAILABLE = True
except ImportError:
    SUPABASE_LIB_AVAILABLE = False

USE_SUPABASE = (
    SUPABASE_LIB_AVAILABLE
    and bool(SUPABASE_URL)
    and bool(SUPABASE_KEY)
)

supabase: "Client | None" = None
if USE_SUPABASE:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Local helper imports ---
from .human_agents import pick_next_agent
from .notifier import send_ticket_email

# --- SQLite setup (fallback) ---
DB_PATH = "data/db/tickets.db"


def _get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    with _get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT UNIQUE,
                created_at TEXT,
                priority TEXT,
                status TEXT DEFAULT 'open',
                issue TEXT,
                customer_mood TEXT,
                conversation_id TEXT,
                assigned_to_name TEXT,
                assigned_to_email TEXT
            )
        """)


# ---------- Public interface ----------

def create_ticket(conversation_id: str, summary: dict, priority: str) -> str:
    """Create a ticket, assign it to a human agent, and notify them by email.

    Returns the sequential ticket ID (e.g. "T-1001").
    """
    if USE_SUPABASE:
        return _create_ticket_supabase(conversation_id, summary, priority)
    return _create_ticket_sqlite(conversation_id, summary, priority)


def list_open_tickets() -> list[dict]:
    """Return all open tickets, newest first (used by the human console)."""
    if USE_SUPABASE:
        return _list_open_tickets_supabase()
    return _list_open_tickets_sqlite()


# ---------- Supabase backend ----------

def _create_ticket_supabase(conversation_id: str, summary: dict, priority: str) -> str:
    # 1. Pick the next human agent using round-robin
    agent = pick_next_agent()

    # 2. Determine the next sequential ticket ID
    result = (
        supabase.table("tickets")
        .select("ticket_id")
        .order("id", desc=True)
        .limit(1)
        .execute()
    )

    last_num = 1000
    if result.data:
        last_ticket_id = result.data[0]["ticket_id"]   # e.g. "T-1003"
        try:
            last_num = int(last_ticket_id.split("-")[1])
        except (IndexError, ValueError):
            last_num = 1000

    ticket_id = f"T-{last_num + 1}"

    # 3. Insert the ticket row with the assigned human agent
    supabase.table("tickets").insert({
        "ticket_id": ticket_id,
        "priority": priority,
        "issue": summary.get("issue", "No issue provided"),
        "customer_mood": summary.get("customer_mood", "unknown"),
        "conversation_id": conversation_id,
        "status": "open",
        "assigned_to_name": agent["name"],
        "assigned_to_email": agent["email"],
    }).execute()

    # 4. Notify the assigned human agent (never raises — logs in mock mode)
    send_ticket_email(
        ticket_id=ticket_id,
        summary=summary,
        priority=priority,
        to_name=agent["name"],
        to_email=agent["email"],
    )

    return ticket_id


def _list_open_tickets_supabase() -> list[dict]:
    result = (
        supabase.table("tickets")
        .select("*")
        .eq("status", "open")
        .order("id", desc=True)
        .execute()
    )
    return result.data


# ---------- SQLite backend (fallback) ----------

def _create_ticket_sqlite(conversation_id: str, summary: dict, priority: str) -> str:
    _init_db()

    # 1. Pick the next human agent using round-robin
    agent = pick_next_agent()

    # 2. Determine the next sequential ticket ID
    with _get_db() as conn:
        cursor = conn.execute(
            "SELECT MAX(CAST(SUBSTR(ticket_id, 3) AS INTEGER)) FROM tickets"
        )
        last_num = cursor.fetchone()[0] or 1000
        ticket_id = f"T-{last_num + 1}"

        # 3. Insert the ticket
        created_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO tickets (
                ticket_id, created_at, priority, issue, customer_mood,
                conversation_id, assigned_to_name, assigned_to_email
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticket_id,
                created_at,
                priority,
                summary.get("issue", "No issue provided"),
                summary.get("customer_mood", "unknown"),
                conversation_id,
                agent["name"],
                agent["email"],
            ),
        )
        conn.commit()

    # 4. Notify the assigned human agent
    send_ticket_email(
        ticket_id=ticket_id,
        summary=summary,
        priority=priority,
        to_name=agent["name"],
        to_email=agent["email"],
    )

    return ticket_id


def _list_open_tickets_sqlite() -> list[dict]:
    _init_db()
    with _get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM tickets WHERE status = 'open' ORDER BY id DESC"
        )
        return [dict(row) for row in cursor.fetchall()]