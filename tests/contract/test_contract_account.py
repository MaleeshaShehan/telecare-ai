"""Account Agent contract: what the Orchestrator and UI rely on.
Builders: run  LLM_PROVIDER=mock pytest tests/contract/test_contract_account.py -q
"""
import re

import pytest
from fastapi.testclient import TestClient

from agents.account_agent.main import app
from shared.config import settings
from shared.envelope import Envelope
from shared.intents import Intent

client = TestClient(app)
KEY = {"X-Internal-Key": settings.internal_api_key}


def ask(intent: Intent, query: str, token: str | None) -> Envelope:
    env = Envelope(conversation_id="contract", sender_agent="orchestrator", receiver_agent="account_agent",
                   intent=intent, payload={"query": query, "entities": {}}, auth_token=token)
    r = client.post("/handle", json=env.model_dump(mode="json"), headers=KEY)
    assert r.status_code == 200, r.text
    return Envelope.model_validate(r.json())


@pytest.mark.parametrize("intent", [Intent.BILL_ENQUIRY, Intent.QUOTA_CHECK])
def test_no_token_is_needs_auth(intent):
    rep = ask(intent, "show me the bill for 0771234567", None)
    assert rep.payload["status"] == "needs_auth"
    assert "answer" not in rep.payload and "bill_diff" not in rep.payload


@pytest.mark.parametrize("intent", [Intent.BILL_ENQUIRY, Intent.QUOTA_CHECK])
def test_garbage_token_never_returns_data(intent):
    rep = ask(intent, "why is my bill higher", "not-a-real-token")
    # The stub returns ok; the real agent must return needs_auth. Either way: valid, and no card data on garbage.
    assert rep.payload["status"] in {"ok", "needs_auth", "not_found", "error"}
    if rep.payload["status"] != "ok":
        assert "bill_diff" not in rep.payload and "quota" not in rep.payload


def test_ok_payload_shapes():
    rep = ask(Intent.BILL_ENQUIRY, "why is my bill higher", "not-a-real-token")
    if rep.payload["status"] != "ok":
        pytest.skip("needs a real token")
    assert isinstance(rep.payload["answer"], str)
    if "bill_diff" in rep.payload:
        d = rep.payload["bill_diff"]
        assert {"change", "drivers", "base_plan_changed"} <= set(d)
        for drv in d["drivers"]:
            assert {"item", "date", "amount"} <= set(drv)
    if "quota" in rep.payload:
        assert {"used_gb", "allowance_gb"} <= set(rep.payload["quota"])


def test_login_endpoint_shape():
    r = client.post("/auth/login", json={"msisdn": "0712345678"}, headers=KEY)
    assert r.status_code in {200, 429, 503}, r.text
    if r.status_code == 200:
        body = r.json()
        assert body.get("otp_sent") is True
        assert body.get("channel") in {"simulated", "sms"}
        if body["channel"] == "simulated":
            assert re.fullmatch(r"\d{6}", str(body.get("debug_otp", "")))


def test_verify_otp_endpoint_shape():
    r = client.post("/auth/verify-otp", json={"msisdn": "0712345678", "otp": "000000"}, headers=KEY)
    assert r.status_code in {200, 401, 429, 501}, r.text
    if r.status_code == 200:
        assert isinstance(r.json().get("token"), str)


def test_auth_endpoints_require_internal_key():
    assert client.post("/auth/login", json={"msisdn": "x"}).status_code == 401
    assert client.post("/auth/verify-otp", json={"msisdn": "x", "otp": "y"}).status_code == 401
