"""Knowledge Agent contract: what the Orchestrator and UI rely on.
These pass against the stub today and must keep passing against the real agent.
Builders: run  LLM_PROVIDER=mock pytest tests/contract/test_contract_knowledge.py -q
"""
import re

import pytest
from fastapi.testclient import TestClient

from agents.knowledge_agent.main import app
from shared.config import settings
from shared.envelope import Envelope
from shared.intents import INTENT_OWNER, Intent

client = TestClient(app)
KEY = {"X-Internal-Key": settings.internal_api_key}
KNOWLEDGE_INTENTS = [i for i, owner in INTENT_OWNER.items() if owner == "knowledge_agent"]


def ask(intent: Intent, query: str) -> Envelope:
    env = Envelope(conversation_id="contract", sender_agent="orchestrator", receiver_agent="knowledge_agent",
                   intent=intent, payload={"query": query, "entities": {}})
    r = client.post("/handle", json=env.model_dump(mode="json"), headers=KEY)
    assert r.status_code == 200, r.text
    return Envelope.model_validate(r.json())


@pytest.mark.parametrize("intent", KNOWLEDGE_INTENTS)
def test_every_knowledge_intent_returns_a_valid_envelope(intent):
    rep = ask(intent, "What is the cheapest 5GB anytime package?")
    assert rep.sender_agent == "knowledge_agent" and rep.receiver_agent == "orchestrator"
    assert rep.intent == intent
    assert rep.payload["status"] in {"ok", "not_found", "error"}


def test_ok_reply_has_answer_and_matching_sources():
    rep = ask(Intent.PACKAGE_INFO, "What is the cheapest 5GB anytime package?")
    if rep.payload["status"] != "ok":
        pytest.skip("stub or empty corpus returned " + rep.payload["status"])
    answer, sources = rep.payload["answer"], rep.payload["sources"]
    assert isinstance(answer, str) and answer.strip()
    assert isinstance(sources, list)
    for s in sources:
        assert {"id", "title", "url", "chunk_id"} <= set(s)
    cited = set(re.findall(r"\[(\d+)\]", answer))
    assert cited <= {str(s["id"]) for s in sources}, "every [n] must have a source with id n"


def test_never_returns_needs_auth_or_escalate():
    for intent in KNOWLEDGE_INTENTS:
        assert ask(intent, "roaming in India").payload["status"] not in {"needs_auth", "escalate"}


def test_not_found_or_error_carry_a_reason():
    rep = ask(Intent.TARIFF_QUERY, "How much is a satellite subscription on the moon?")
    if rep.payload["status"] in {"not_found", "error"}:
        assert isinstance(rep.payload.get("reason"), str) and rep.payload["reason"]


def test_rejects_call_without_internal_key():
    env = Envelope(conversation_id="c", sender_agent="orchestrator", receiver_agent="knowledge_agent",
                   intent=Intent.PACKAGE_INFO, payload={"query": "x", "entities": {}})
    assert client.post("/handle", json=env.model_dump(mode="json")).status_code == 401
