"""This month vs last month, pure Python. No LLM in this file.   Owner: M3

    diff(this_bill: dict, last_bill: dict, this_items: list[dict], last_items: list[dict]) -> dict

Returns e.g.
    {"change": 1200,
     "drivers": [{"item": "Data add-on 10GB", "date": "2026-10-12", "amount": 1200}],
     "base_plan_changed": False}

Tests: tests/test_bill_diff.py
"""

from collections import defaultdict
from decimal import Decimal


def _decimal(value: object) -> Decimal:
    return Decimal(str(value or 0))


def _number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _total(bill: dict) -> Decimal:
    return _decimal(bill.get("total_amount", bill.get("total", 0)))


def _category(item: dict) -> str:
    return str(item.get("category", item.get("type", "other")))


def _date(item: dict) -> str:
    value = str(item.get("occurred_at", item.get("item_date", "")))
    return value[:10]


def _base_total(items: list[dict], bill: dict) -> Decimal:
    values = [
        _decimal(item.get("amount"))
        for item in items
        if _category(item) in {"base", "base_plan"}
    ]
    if values:
        return sum(values, Decimal("0"))
    return _decimal(bill.get("base_fee", 0))


def diff(this_bill: dict, last_bill: dict, this_items: list[dict], last_items: list[dict]) -> dict:
    """Compare two immutable bills without involving an LLM."""
    previous_by_description: dict[str, Decimal] = defaultdict(Decimal)
    for item in last_items:
        if _category(item) not in {"base", "base_plan", "tax"}:
            previous_by_description[str(item.get("description", "Charge"))] += _decimal(
                item.get("amount")
            )

    current_by_description: dict[str, Decimal] = defaultdict(Decimal)
    current_dates: dict[str, str] = {}
    for item in this_items:
        if _category(item) not in {"base", "base_plan", "tax"}:
            description = str(item.get("description", "Charge"))
            current_by_description[description] += _decimal(item.get("amount"))
            current_dates.setdefault(description, _date(item))

    drivers: list[dict] = []
    for description in sorted(set(previous_by_description) | set(current_by_description)):
        change = current_by_description[description] - previous_by_description[description]
        if change:
            drivers.append(
                {
                    "item": description,
                    "date": current_dates.get(description, ""),
                    "amount": _number(change),
                }
            )
    drivers.sort(key=lambda driver: abs(float(driver["amount"])), reverse=True)

    return {
        "change": _number(_total(this_bill) - _total(last_bill)),
        "drivers": drivers,
        "base_plan_changed": _base_total(this_items, this_bill)
        != _base_total(last_items, last_bill),
    }
