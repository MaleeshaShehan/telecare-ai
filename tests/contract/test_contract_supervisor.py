"""Supervisor Agent contract: what the Orchestrator and UI rely on.
Builders: run  LLM_PROVIDER=mock pytest tests/contract/test_contract_supervisor.py -q
"""
import re

from fastapi.testclient import TestClient

from agents.supervisor_agent.main import app
from shared.config import settings
from shared.envelope import Envelope
from shared.intents import Intent

client = TestClient(app)
KEY = {"X-Internal-Key": settings.internal_api_key}


def call(payload: dict, intent: Intent = Intent.COMPLAINT) -> Envelope:
    env = Envelope(conversation_id="contract", sender_agent="orchestrator", receiver_agent="supervisor_agent",
                   intent=intent, payload=payload)
    r = client.post("/handle", json=env.model_dump(mode="json"), headers=KEY)
    assert r.status_code == 200, r.text
    return Envelope.model_validate(r.json())


def test_assess_shape():
    rep = call({"task": "assess", "message": "What does Anytime 5GB include?", "intent": "package_info", "failed_count": 0},
               Intent.PACKAGE_INFO)
    p = rep.payload
    assert p["status"] == "ok"
    assert p["sentiment"] in {"positive", "neutral", "negative"}
    assert isinstance(p["score"], (int, float)) and -1.0 <= p["score"] <= 1.0
    assert isinstance(p["escalate"], bool)
    assert isinstance(p["reason"], str)
    assert p["priority"] in {"high", "normal", "low"}


def test_assess_is_fast_enough_for_every_turn():
    import time
    t = time.perf_counter()
    for _ in range(5):
        call({"task": "assess", "message": "hello", "intent": "package_info", "failed_count": 0}, Intent.PACKAGE_INFO)
    assert (time.perf_counter() - t) / 5 < 0.5, "assess runs on every turn; keep VADER local, LLM only for borderline"


def test_escalate_shape():
    rep = call({"task": "escalate",
                "history": [{"role": "user", "text": "My number is 0712345678 and this is ridiculous"}],
                "reason": "vader<=-0.5", "priority": "high"})
    p = rep.payload
    assert p["status"] == "escalate"
    assert re.fullmatch(r"T-\d{4}", p["ticket_id"])
    assert isinstance(p["answer"], str) and p["ticket_id"] in p["answer"]


def test_tickets_endpoint_is_a_list_and_pii_free():
    r = client.get("/tickets", headers=KEY)
    assert r.status_code == 200
    tickets = r.json()
    assert isinstance(tickets, list)
    for t in tickets:
        assert {"ticket_id", "priority", "status"} <= set(t)
        blob = str(t)
        assert not re.search(r"(?:\+94|0)7\d{8}", blob), "phone number leaked into a ticket"
        assert not re.search(r"\b\d{9}[VvXx]\b|\b\d{12}\b", blob), "NIC leaked into a ticket"


def test_requires_internal_key():
    env = Envelope(conversation_id="c", sender_agent="orchestrator", receiver_agent="supervisor_agent",
                   intent=Intent.COMPLAINT, payload={"task": "assess", "message": "x", "intent": "complaint", "failed_count": 0})
    assert client.post("/handle", json=env.model_dump(mode="json")).status_code == 401
    assert client.get("/tickets").status_code == 401
