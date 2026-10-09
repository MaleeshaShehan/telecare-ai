"""Subscriber-scoped data access for SQLite tests and Supabase runtime."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import httpx

from shared.config import settings


DB_PATH = Path(__file__).resolve().parents[2] / "data" / "db" / "telecare.db"


class RepositoryError(RuntimeError):
    """The configured account data store could not satisfy a request."""


def using_supabase() -> bool:
    return settings.account_db_backend.strip().lower() == "supabase"


def connect() -> sqlite3.Connection:
    """Open the local fallback database read-only."""
    conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _supabase_headers() -> dict[str, str]:
    if not settings.supabase_url or not settings.supabase_key:
        raise RepositoryError("Supabase is selected but its server credentials are missing")
    return {
        "apikey": settings.supabase_key,
        "Authorization": f"Bearer {settings.supabase_key}",
    }


def _select(table: str, **params: str) -> list[dict[str, Any]]:
    url = f"{settings.supabase_url.rstrip('/')}/rest/v1/{table}"
    try:
        response = httpx.get(
            url, params=params, headers=_supabase_headers(), timeout=10.0
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RepositoryError(f"Supabase read failed for {table}") from exc
    if not isinstance(payload, list):
        raise RepositoryError(f"Unexpected Supabase response for {table}")
    return payload


def _supabase_msisdn(local_msisdn: str) -> str:
    return f"94{local_msisdn[1:]}" if local_msisdn.startswith("0") else local_msisdn


def find_subscriber_by_msisdn(msisdn: str) -> dict[str, Any] | None:
    """Return only the identity fields needed for authentication."""
    if using_supabase():
        rows = _select(
            "subscribers",
            select="subscriber_id,msisdn,account_status",
            msisdn=f"eq.{_supabase_msisdn(msisdn)}",
            limit="1",
        )
        return rows[0] if rows else None
    with connect() as conn:
        row = conn.execute(
            "SELECT subscriber_id, msisdn FROM subscribers WHERE msisdn = ?",
            (msisdn,),
        ).fetchone()
    return dict(row) if row else None


def subscriber_exists(subscriber_id: str) -> bool:
    if using_supabase():
        return bool(
            _select(
                "subscribers",
                select="subscriber_id",
                subscriber_id=f"eq.{subscriber_id}",
                account_status="eq.active",
                limit="1",
            )
        )
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM subscribers WHERE subscriber_id = ?", (subscriber_id,)
        ).fetchone()
    return row is not None


def get_bills(subscriber_id: str, limit: int = 2) -> list[dict[str, Any]]:
    if using_supabase():
        return _select(
            "bills",
            select="bill_id,subscriber_id,billing_period_start,billing_period_end,issued_at,due_date,subtotal,tax_amount,total_amount,amount_paid,amount_due,currency,status",
            subscriber_id=f"eq.{subscriber_id}",
            status="in.(issued,partially_paid,paid,overdue)",
            order="billing_period_end.desc",
            limit=str(limit),
        )
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM bills WHERE subscriber_id = ? ORDER BY period DESC LIMIT ?",
            (subscriber_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_bill_for_period(subscriber_id: str, period: str) -> dict[str, Any] | None:
    """Return one subscriber-owned bill for a YYYY-MM billing period."""
    period_start = f"{period}-01"
    if using_supabase():
        rows = _select(
            "bills",
            select="bill_id,subscriber_id,billing_period_start,billing_period_end,issued_at,due_date,subtotal,tax_amount,total_amount,amount_paid,amount_due,currency,status",
            subscriber_id=f"eq.{subscriber_id}",
            billing_period_start=f"eq.{period_start}",
            status="in.(issued,partially_paid,paid,overdue)",
            limit="1",
        )
        return rows[0] if rows else None
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM bills WHERE subscriber_id = ? AND period = ?",
            (subscriber_id, period),
        ).fetchone()
    return dict(row) if row else None


def get_bill_items(subscriber_id: str, bill_id: str | int) -> list[dict[str, Any]]:
    """Return items only after proving the bill belongs to this subscriber."""
    if using_supabase():
        owned = _select(
            "bills",
            select="bill_id",
            bill_id=f"eq.{bill_id}",
            subscriber_id=f"eq.{subscriber_id}",
            limit="1",
        )
        if not owned:
            return []
        return _select(
            "bill_items",
            select="category,description,quantity,unit_price,amount,occurred_at,metadata",
            bill_id=f"eq.{bill_id}",
            order="occurred_at.asc",
        )
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT i.* FROM bill_items AS i
            JOIN bills AS b ON b.bill_id = i.bill_id
            WHERE i.bill_id = ? AND b.subscriber_id = ?
            ORDER BY i.item_date ASC
            """,
            (bill_id, subscriber_id),
        ).fetchall()
    return [dict(row) for row in rows]


def get_usage(subscriber_id: str) -> dict[str, Any] | None:
    if using_supabase():
        rows = _select(
            "usage",
            select="subscriber_id,period_start,period_end,data_used_mb,voice_minutes_used,sms_used,roaming_data_mb",
            subscriber_id=f"eq.{subscriber_id}",
            order="period_end.desc",
            limit="1",
        )
        return rows[0] if rows else None
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM usage WHERE subscriber_id = ? ORDER BY period DESC LIMIT 1",
            (subscriber_id,),
        ).fetchone()
    return dict(row) if row else None


def get_plan(subscriber_id: str) -> dict[str, Any] | None:
    if using_supabase():
        subscribers = _select(
            "subscribers",
            select="plan_id",
            subscriber_id=f"eq.{subscriber_id}",
            limit="1",
        )
        if not subscribers or not subscribers[0].get("plan_id"):
            return None
        rows = _select(
            "plans",
            select="plan_id,plan_name,monthly_fee,data_quota_mb,voice_quota_minutes,sms_quota,is_active",
            plan_id=f"eq.{subscribers[0]['plan_id']}",
            limit="1",
        )
        return rows[0] if rows else None
    with connect() as conn:
        row = conn.execute(
            """
            SELECT p.* FROM plans AS p
            JOIN subscribers AS s ON s.plan_id = p.plan_id
            WHERE s.subscriber_id = ?
            """,
            (subscriber_id,),
        ).fetchone()
    return dict(row) if row else None


def get_payments(subscriber_id: str, limit: int = 3) -> list[dict[str, Any]]:
    if using_supabase():
        return _select(
            "payments",
            select="payment_id,bill_id,amount,currency,payment_method,transaction_reference,paid_at,status",
            subscriber_id=f"eq.{subscriber_id}",
            order="paid_at.desc",
            limit=str(limit),
        )
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM payments WHERE subscriber_id = ? ORDER BY paid_on DESC LIMIT ?",
            (subscriber_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]
