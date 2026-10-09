"""Every specialist rejects calls without the X-Internal-Key header."""
import pytest
from fastapi.testclient import TestClient

from agents.account_agent.main import app as account_app
from agents.knowledge_agent.main import app as knowledge_app
from agents.supervisor_agent.main import app as supervisor_app
from shared.config import settings
from shared.envelope import Envelope
from shared.intents import Intent

ENV = Envelope(conversation_id="c", sender_agent="orchestrator", receiver_agent="knowledge_agent",
               intent=Intent.PACKAGE_INFO, payload={"query": "x"}).model_dump(mode="json")


@pytest.mark.parametrize("app", [knowledge_app, account_app, supervisor_app])
def test_missing_key_is_401(app):
    assert TestClient(app).post("/handle", json=ENV).status_code == 401


@pytest.mark.parametrize("app", [knowledge_app, account_app, supervisor_app])
def test_wrong_key_is_401(app):
    assert TestClient(app).post("/handle", json=ENV, headers={"X-Internal-Key": "nope"}).status_code == 401


@pytest.mark.parametrize("app", [knowledge_app, account_app, supervisor_app])
def test_correct_key_returns_envelope(app):
    r = TestClient(app).post("/handle", json=ENV, headers={"X-Internal-Key": settings.internal_api_key})
    assert r.status_code == 200
    body = Envelope.model_validate(r.json())
    assert body.receiver_agent == "orchestrator"
    assert "status" in body.payload


def test_account_agent_without_token_says_needs_auth():
    r = TestClient(account_app).post("/handle", json=ENV, headers={"X-Internal-Key": settings.internal_api_key})
    assert r.json()["payload"]["status"] == "needs_auth"


def test_empty_configured_key_fails_closed(monkeypatch):
    """An empty INTERNAL_API_KEY must not let an empty header through."""
    monkeypatch.setattr(settings, "internal_api_key", "")
    r = TestClient(knowledge_app).post("/handle", json=ENV, headers={"X-Internal-Key": ""})
    assert r.status_code == 401
