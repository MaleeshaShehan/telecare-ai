"""Import a validated synthetic TeleCare JSON dataset into Supabase.

The source JSON contains synthetic plaintext PII.  This importer encrypts
name, email, and NIC with the project's Fernet key before any network write.
It never writes OTP challenges and never logs PII or credentials.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

import httpx
from cryptography.fernet import Fernet

from shared.config import settings


BATCH_SIZE = 100


def _chunks(rows: list[Any], size: int = BATCH_SIZE) -> Iterable[list[Any]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


class SupabaseDataAPI:
    def __init__(self, url: str, key: str) -> None:
        self.client = httpx.Client(
            base_url=f"{url.rstrip('/')}/rest/v1/",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def close(self) -> None:
        self.client.close()

    def _request(self, method: str, table: str, **kwargs: Any) -> httpx.Response:
        response = self.client.request(method, table, **kwargs)
        if response.is_error:
            detail = response.text[:1000]
            raise RuntimeError(
                f"Supabase {method} {table} failed with "
                f"HTTP {response.status_code}: {detail}"
            )
        return response

    def upsert(self, table: str, rows: list[dict[str, Any]], conflict: str) -> None:
        for batch in _chunks(rows):
            self._request(
                "POST",
                table,
                params={"on_conflict": conflict},
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                json=batch,
            )

    def insert(self, table: str, rows: list[dict[str, Any]]) -> None:
        for batch in _chunks(rows):
            self._request(
                "POST",
                table,
                headers={"Prefer": "return=minimal"},
                json=batch,
            )

    def delete_for_bill_ids(self, bill_ids: list[str]) -> None:
        for batch in _chunks(bill_ids, 20):
            self._request(
                "DELETE",
                "bill_items",
                params={"bill_id": f"in.({','.join(batch)})"},
                headers={"Prefer": "return=minimal"},
            )

    def select(self, table: str, **params: str) -> list[dict[str, Any]]:
        response = self._request("GET", table, params=params)
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError(f"Unexpected Supabase response for {table}")
        return payload


def _load_dataset(path: Path) -> dict[str, Any]:
    dataset = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "plans",
        "subscribers",
        "bills",
        "bill_items",
        "usage",
        "payments",
    }
    missing = required.difference(dataset)
    if missing:
        raise SystemExit(f"Dataset is missing sections: {', '.join(sorted(missing))}")
    if len(dataset["subscribers"]) != 40 or len(dataset["bills"]) != 80:
        raise SystemExit("Expected exactly 40 subscribers and 80 bills")
    if "otp_challenges" in dataset:
        raise SystemExit("Refusing dataset containing OTP challenges")
    return dataset


def _encrypted_subscribers(
    subscribers: list[dict[str, Any]], cipher: Fernet
) -> list[dict[str, Any]]:
    encrypted: list[dict[str, Any]] = []
    for subscriber in subscribers:
        encrypted.append(
            {
                "subscriber_id": subscriber["subscriber_id"],
                "msisdn": subscriber["msisdn"],
                "full_name_encrypted": cipher.encrypt(
                    subscriber["full_name"].encode("utf-8")
                ).decode("ascii"),
                "email_encrypted": cipher.encrypt(
                    subscriber["email"].encode("utf-8")
                ).decode("ascii"),
                "nic_encrypted": cipher.encrypt(
                    subscriber["nic"].encode("utf-8")
                ).decode("ascii"),
                "plan_id": subscriber["plan_id"],
                "account_status": subscriber["account_status"],
            }
        )
    return encrypted


def _expected_ids(rows: list[dict[str, Any]], field: str) -> set[str]:
    return {str(row[field]) for row in rows}


def _verify(api: SupabaseDataAPI, dataset: dict[str, Any]) -> dict[str, int]:
    expected_plan_ids = _expected_ids(dataset["plans"], "plan_id")
    expected_subscriber_ids = _expected_ids(dataset["subscribers"], "subscriber_id")
    expected_bill_ids = _expected_ids(dataset["bills"], "bill_id")
    expected_payment_ids = _expected_ids(dataset["payments"], "payment_id")

    plans = api.select("plans", select="plan_id")
    subscribers = api.select(
        "subscribers", select="subscriber_id", subscriber_id="like.SUB-*"
    )
    bills = api.select("bills", select="bill_id", bill_id="like.BILL-SUB-*")
    payments = api.select(
        "payments", select="payment_id", payment_id="like.PAY-SUB-*"
    )
    usage = api.select(
        "usage",
        select="subscriber_id",
        period_start="eq.2026-10-01",
        subscriber_id=f"in.({','.join(sorted(expected_subscriber_ids))})",
    )

    bill_items: list[dict[str, Any]] = []
    for batch in _chunks(sorted(expected_bill_ids), 20):
        bill_items.extend(
            api.select(
                "bill_items",
                select="bill_id",
                bill_id=f"in.({','.join(batch)})",
            )
        )

    otp_rows = api.select("otp_challenges", select="msisdn_hash", limit="1")

    checks = {
        "plans": expected_plan_ids.issubset(_expected_ids(plans, "plan_id")),
        "subscribers": _expected_ids(subscribers, "subscriber_id")
        == expected_subscriber_ids,
        "bills": _expected_ids(bills, "bill_id") == expected_bill_ids,
        "bill_items": len(bill_items) == len(dataset["bill_items"]),
        "usage": _expected_ids(usage, "subscriber_id") == expected_subscriber_ids,
        "payments": _expected_ids(payments, "payment_id") == expected_payment_ids,
        "otp_challenges_empty": len(otp_rows) == 0,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f"Remote verification failed: {', '.join(failed)}")

    return {
        "plans": len(expected_plan_ids),
        "subscribers": len(expected_subscriber_ids),
        "bills": len(expected_bill_ids),
        "bill_items": len(bill_items),
        "usage": len(usage),
        "payments": len(expected_payment_ids),
        "otp_challenges": len(otp_rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()

    if not settings.supabase_url or not settings.supabase_key:
        raise SystemExit("SUPABASE_URL and SUPABASE_KEY must be set in .env")
    if not settings.fernet_key:
        raise SystemExit("FERNET_KEY must be set in .env")

    dataset = _load_dataset(args.dataset)
    cipher = Fernet(settings.fernet_key.encode("ascii"))
    subscribers = _encrypted_subscribers(dataset["subscribers"], cipher)
    bill_ids = sorted(_expected_ids(dataset["bills"], "bill_id"))

    api = SupabaseDataAPI(settings.supabase_url, settings.supabase_key)
    try:
        api.upsert("plans", dataset["plans"], "plan_id")
        api.upsert("subscribers", subscribers, "subscriber_id")
        api.upsert("bills", dataset["bills"], "bill_id")

        # Identity-keyed bill items are replaced only for our synthetic bills.
        api.delete_for_bill_ids(bill_ids)
        api.insert("bill_items", dataset["bill_items"])

        api.upsert(
            "usage",
            dataset["usage"],
            "subscriber_id,period_start,period_end",
        )
        api.upsert("payments", dataset["payments"], "payment_id")

        counts = _verify(api, dataset)
    finally:
        api.close()

    print("Supabase synthetic-data import succeeded:")
    for table, count in counts.items():
        print(f"- {table}: {count}")


if __name__ == "__main__":
    main()
