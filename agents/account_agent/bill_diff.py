"""This month vs last month, pure Python. No LLM in this file.   Owner: M3

    diff(this_bill: dict, last_bill: dict, this_items: list[dict], last_items: list[dict]) -> dict

Returns e.g.
    {"change": 1200,
     "drivers": [{"item": "Data add-on 10GB", "date": "2026-10-12", "amount": 1200}],
     "base_plan_changed": False}

Tests: tests/test_bill_diff.py
"""


def diff(this_bill: dict, last_bill: dict, this_items: list[dict], last_items: list[dict]) -> dict:
    raise NotImplementedError("M3")
