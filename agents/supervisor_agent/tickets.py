"""Ticket store. Uses Supabase if credentials are provided, else SQLite.   Owner: M4

    create_ticket(conversation_id, summary: dict, priority) -> str
    list_open_tickets() -> list[dict]

Dual-backend:
    - If SUPABASE_URL + SUPABASE_KEY are set in .env → use Supabase Postgres (cloud).
    - Otherwise → fall back to SQLite (local, used for offline tests).
"""
import os
import sqlite3
from datetime import datetime, timezone

# Load .env so we can read SUPABASE_URL and SUPABASE_KEY directly.
# (shared/config.py does not yet expose them — this avoids editing M1's code.)
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

# --- Supabase setup (optional) ---
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
                conversation_id TEXT
            )
        """)


# ---------- Public interface ----------

def create_ticket(conversation_id: str, summary: dict, priority: str) -> str:
    if USE_SUPABASE:
        return _create_ticket_supabase(conversation_id, summary, priority)
    return _create_ticket_sqlite(conversation_id, summary, priority)


def list_open_tickets() -> list[dict]:
    if USE_SUPABASE:
        return _list_open_tickets_supabase()
    return _list_open_tickets_sqlite()


# ---------- Supabase backend ----------

def _create_ticket_supabase(conversation_id: str, summary: dict, priority: str) -> str:
    # Get the highest ticket number used so far
    result = (
        supabase.table("tickets")
        .select("ticket_id")
        .order("id", desc=True)
        .limit(1)
        .execute()
    )

    last_num = 1000
    if result.data:
        last_ticket_id = result.data[0]["ticket_id"]  # e.g. "T-1003"
        last_num = int(last_ticket_id.split("-")[1])

    ticket_id = f"T-{last_num + 1}"

    supabase.table("tickets").insert({
        "ticket_id": ticket_id,
        "priority": priority,
        "issue": summary.get("issue", "No issue provided"),
        "customer_mood": summary.get("customer_mood", "unknown"),
        "conversation_id": conversation_id,
        "status": "open",
    }).execute()

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
    with _get_db() as conn:
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


def _list_open_tickets_sqlite() -> list[dict]:
    _init_db()
    with _get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM tickets WHERE status = 'open' ORDER BY id DESC"
        )
        return [dict(row) for row in cursor.fetchall()]