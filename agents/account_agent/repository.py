"""Read-only, parameterised SQL against telecare.db.   Owner: M3

Every function takes subscriber_id (from the JWT) and filters on it.

    connect() -> sqlite3.connect("file:data/db/telecare.db?mode=ro", uri=True)
    get_bills(subscriber_id, periods: tuple[str, str]) -> list[dict]
    get_bill_items(bill_id) -> list[dict]
    get_usage(subscriber_id, period) -> dict
    get_plan(subscriber_id) -> dict
    get_payments(subscriber_id, limit=3) -> list[dict]
"""
import sqlite3

DB_URI = "file:data/db/telecare.db?mode=ro"


def connect() -> sqlite3.Connection:
    """Read-only connection. Any write raises sqlite3.OperationalError."""
    conn = sqlite3.connect(DB_URI, uri=True)
    conn.row_factory = sqlite3.Row
    return conn
