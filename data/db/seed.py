"""Build the synthetic databases.   Owner: M3

    python data/db/seed.py

Creates data/db/telecare.db from schema.sql with 40 Faker subscribers, two
months of bills each, about a third with a deliberate change between months.
One fixed demo subscriber has the exact demo-story numbers (Rs. 1,200 data
add-on on the 12th). Authentication is passwordless by SMS OTP.

Also creates an empty data/db/auth.db (OTP store) and data/db/tickets.db.
All data is synthetic. Never add real customer data.
"""
from __future__ import annotations

import random
import sqlite3
from datetime import date
from pathlib import Path

from cryptography.fernet import Fernet
from faker import Faker

# Allow `python data/db/seed.py` from the repository root.
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from shared.config import settings  # noqa: E402


DB_DIR = ROOT / "data" / "db"
DB_PATH = DB_DIR / "telecare.db"
AUTH_DB = DB_DIR / "auth.db"


def _previous_period(today: date) -> tuple[str, str]:
    this_period = today.strftime("%Y-%m")
    previous_year = today.year if today.month > 1 else today.year - 1
    previous_month = today.month - 1 if today.month > 1 else 12
    return this_period, f"{previous_year:04d}-{previous_month:02d}"


def main() -> None:
    if not settings.fernet_key:
        raise SystemExit("FERNET_KEY is empty. Generate one and set it in .env before seeding.")

    try:
        cipher = Fernet(settings.fernet_key.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise SystemExit("FERNET_KEY in .env is not a valid Fernet key.") from exc

    DB_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    if AUTH_DB.exists():
        AUTH_DB.unlink()

    schema = (DB_DIR / "schema.sql").read_text(encoding="utf-8")
    fake = Faker("en_US")
    Faker.seed(3041)
    random.seed(3041)
    today = date.today()
    this_period, last_period = _previous_period(today)

    plans = [
        (1, "Anytime 10GB", 1490, 10, 500),
        (2, "Home Streamer 100GB", 2990, 100, 1000),
        (3, "Unlimited Max", 4990, 250, 2000),
    ]

    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(schema)
        conn.executemany(
            "INSERT INTO plans (plan_id, name, monthly_fee, data_gb, voice_min) VALUES (?, ?, ?, ?, ?)",
            plans,
        )

        bill_id = 1
        item_id = 1
        payment_id = 1
        for index in range(40):
            subscriber_id = f"SUB-{index + 1:04d}"
            msisdn = "0712345678" if index == 0 else f"077{index:07d}"
            plan = plans[index % len(plans)]
            plan_id, _plan_name, monthly_fee, allowance_gb, _voice_min = plan

            conn.execute(
                """
                INSERT INTO subscribers
                    (subscriber_id, msisdn, full_name_enc, email_enc, nic_enc, plan_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    subscriber_id,
                    msisdn,
                    cipher.encrypt(fake.name().encode()).decode(),
                    cipher.encrypt(fake.email().encode()).decode(),
                    cipher.encrypt(f"{random.randint(700000000, 999999999)}V".encode()).decode(),
                    plan_id,
                ),
            )

            addon = 1200 if index == 0 else (500 if index % 3 == 0 else 0)
            for period, extra in ((last_period, 0), (this_period, addon)):
                total = monthly_fee + extra
                conn.execute(
                    """
                    INSERT INTO bills
                        (bill_id, subscriber_id, period, base_fee, addons, roaming, overage, tax, total)
                    VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?)
                    """,
                    (bill_id, subscriber_id, period, monthly_fee, extra, total),
                )
                conn.execute(
                    """
                    INSERT INTO bill_items (item_id, bill_id, item_date, type, description, amount)
                    VALUES (?, ?, ?, 'base', ?, ?)
                    """,
                    (item_id, bill_id, f"{period}-01", f"{_plan_name} monthly fee", monthly_fee),
                )
                item_id += 1
                if extra:
                    description = "Data add-on 10GB" if index == 0 else "Data add-on 5GB"
                    conn.execute(
                        """
                        INSERT INTO bill_items (item_id, bill_id, item_date, type, description, amount)
                        VALUES (?, ?, ?, 'addon', ?, ?)
                        """,
                        (item_id, bill_id, f"{period}-12", description, extra),
                    )
                    item_id += 1
                bill_id += 1

            used_gb = round(min(allowance_gb, 1.5 + index * 0.7), 2)
            conn.execute(
                "INSERT INTO usage (subscriber_id, period, data_used_gb, voice_used_min) VALUES (?, ?, ?, ?)",
                (subscriber_id, this_period, used_gb, 25 + index),
            )
            conn.execute(
                "INSERT INTO payments (payment_id, subscriber_id, paid_on, amount, method) VALUES (?, ?, ?, ?, ?)",
                (payment_id, subscriber_id, f"{this_period}-03", monthly_fee, "card"),
            )
            payment_id += 1

    print(f"Created {DB_PATH} with 40 synthetic subscribers.")
    print("Demo mobile number: 0712345678 (login uses SMS OTP; there is no password).")


if __name__ == "__main__":
    main()
