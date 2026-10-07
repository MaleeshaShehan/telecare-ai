"""bill_diff is pure Python. Owner: M3. Remove the skip when implemented."""
import pytest

from agents.account_agent.bill_diff import diff

THIS = {"bill_id": 2, "period": "2026-10", "base_fee": 1500, "addons": 1200, "roaming": 0, "overage": 0, "tax": 0, "total": 2700}
LAST = {"bill_id": 1, "period": "2026-09", "base_fee": 1500, "addons": 0, "roaming": 0, "overage": 0, "tax": 0, "total": 1500}
THIS_ITEMS = [{"item_date": "2026-10-12", "type": "addon", "description": "Data add-on 10GB", "amount": 1200}]
LAST_ITEMS: list[dict] = []


@pytest.mark.xfail(raises=NotImplementedError, reason="M3 to implement", strict=True)
def test_demo_story_add_on_on_the_12th():
    out = diff(THIS, LAST, THIS_ITEMS, LAST_ITEMS)
    assert out["change"] == 1200
    assert out["base_plan_changed"] is False
    assert out["drivers"] == [{"item": "Data add-on 10GB", "date": "2026-10-12", "amount": 1200}]
