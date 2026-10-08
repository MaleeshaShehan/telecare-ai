"""The full demo story through the Orchestrator, LLM in mock mode, specialists faked
to return exactly what the real ones will (BUILD_PLAN section 5 demo story).

  1. "Why is my bill higher this month?"       -> needs_auth
  2. login + OTP                               -> token stored
  3. same question again                       -> Account Agent: Rs. 1,200 add-on on the 12th
  4. "I stream video at home... what plan?"    -> Knowledge Agent: cited plan advice
  5. "This is ridiculous, weeks of problems!"  -> Supervisor: ticket T-1042
"""
from fastapi.testclient import TestClient

from agents.orchestrator import main, router
from agents.orchestrator.main import app
from shared.envelope import Envelope, make_reply

client = TestClient(app)

BILL_ANSWER = "Your bill went up Rs. 1,200 from a data add-on on the 12th; your base plan is unchanged."
PLAN_ANSWER = "Home Streamer 100GB suits evening video [1]. This is a suggestion; check the details before switching."
TICKET_ANSWER = "I'm sorry about the trouble. I've created ticket T-1042; a human agent will call within 24 hours."


def fake_specialists(env: Envelope) -> Envelope:
    if env.receiver_agent == "supervisor_agent":
        if env.payload["task"] == "escalate":
            return make_reply(env, "escalate", {"ticket_id": "T-1042", "answer": TICKET_ANSWER})
        angry = "ridiculous" in env.payload["message"].lower()
        return make_reply(env, "ok", {"sentiment": "negative" if angry else "neutral", "score": -0.7 if angry else 0.1,
                                      "escalate": angry, "reason": "vader<=-0.5" if angry else "", "priority": "high"})
    if env.receiver_agent == "account_agent":
        assert env.auth_token == "jwt-demo", "account agent must receive the session token"
        return make_reply(env, "ok", {"answer": BILL_ANSWER})
    if env.receiver_agent == "knowledge_agent":
        return make_reply(env, "ok", {"answer": PLAN_ANSWER,
                                      "sources": [{"id": 1, "title": "Home Packages", "url": "https://op.lk/home", "chunk_id": "D004-3"}]})
    raise AssertionError(env.receiver_agent)


def test_demo_story(monkeypatch, fresh_session):
    cid = fresh_session
    monkeypatch.setattr(router, "call_agent", fake_specialists)
    monkeypatch.setattr(main, "_proxy_account", lambda path, body: {
        "/auth/login": (200, {"otp_sent": True, "debug_otp": "482913"}),
        "/auth/verify-otp": (200, {"token": "jwt-demo"}),
    }[path])

    def say(text):
        return client.post("/chat", json={"conversation_id": cid, "message": text},
                           headers={"X-Conversation-Id": cid}).json()

    # 1. Bill question before login
    r1 = say("Why is my bill higher this month?")
    assert r1["status"] == "needs_auth"
    assert r1["reply"].startswith("Hi, I'm TeleCare's AI assistant.")

    # 2. Login + OTP
    assert client.post("/auth/login", json={"conversation_id": cid, "msisdn": "0712345678"}).status_code == 200
    assert client.post("/auth/verify-otp", json={"conversation_id": cid, "msisdn": "0712345678", "otp": "482913"}).json()["logged_in"]

    # 3. Same question, now answered from the account
    r3 = say("Why is my bill higher this month?")
    assert r3["status"] == "ok"
    assert "Rs. 1,200" in r3["reply"] and "12th" in r3["reply"]
    assert not r3["reply"].startswith("Hi, I'm")      # disclosure only once

    # 4. Plan advice with a cited source
    r4 = say("That's too much. I mostly stream video at home in the evenings, what plan suits me?")
    assert r4["status"] == "ok"
    assert "[1]" in r4["reply"]
    assert r4["sources"][0]["title"] == "Home Packages"

    # 5. Frustration -> ticket
    r5 = say("This is ridiculous, I've had billing problems for weeks!")
    assert r5["status"] == "escalate"
    assert "T-1042" in r5["reply"]

    # The trace tells the whole story without any message text
    decisions = [t["decision"] for t in r5["trace"]]
    for expected in ("auth_required", "otp_verified", "route->account_agent", "route->knowledge_agent", "escalate", "result=escalate"):
        assert expected in decisions, expected
    assert not any("ridiculous" in t["reason"] for t in r5["trace"])
