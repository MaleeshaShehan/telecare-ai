from datetime import datetime

import pytest
from pydantic import ValidationError

from shared.envelope import STATUS_VALUES, Envelope, make_reply
from shared.intents import AUTH_REQUIRED, INTENT_OWNER, Intent


def _req() -> Envelope:
    return Envelope(conversation_id="c1", sender_agent="orchestrator", receiver_agent="knowledge_agent",
                    intent=Intent.PACKAGE_INFO, payload={"query": "cheapest 5GB"}, auth_token="jwt")


def test_envelope_has_exactly_eight_fields():
    assert set(Envelope.model_fields) == {
        "message_id", "conversation_id", "sender_agent", "receiver_agent",
        "intent", "payload", "auth_token", "timestamp",
    }


def test_defaults_are_filled():
    env = _req()
    assert len(env.message_id) == 36
    assert isinstance(env.timestamp, datetime)


def test_reply_swaps_sender_and_receiver_and_drops_token():
    req = _req()
    rep = make_reply(req, "ok", {"answer": "x"})
    assert rep.sender_agent == "knowledge_agent"
    assert rep.receiver_agent == "orchestrator"
    assert rep.conversation_id == req.conversation_id
    assert rep.intent == req.intent
    assert rep.payload == {"status": "ok", "answer": "x"}
    assert rep.auth_token is None


def test_reply_without_result_has_only_status():
    assert make_reply(_req(), "needs_auth").payload == {"status": "needs_auth"}


def test_unknown_agent_or_intent_rejected():
    with pytest.raises(ValidationError):
        Envelope(conversation_id="c", sender_agent="hacker", receiver_agent="orchestrator",
                 intent=Intent.PACKAGE_INFO, payload={})
    with pytest.raises(ValidationError):
        Envelope(conversation_id="c", sender_agent="orchestrator", receiver_agent="knowledge_agent",
                 intent="not_an_intent", payload={})


def test_round_trips_through_json():
    env = _req()
    assert Envelope.model_validate_json(env.model_dump_json()) == env


def test_every_intent_has_an_owner():
    assert set(INTENT_OWNER) == set(Intent)
    assert AUTH_REQUIRED == {
        Intent.BILL_ENQUIRY,
        Intent.BILL_BY_MONTH,
        Intent.QUOTA_CHECK,
        Intent.ACTIVE_PACKAGE_DETAILS,
    }
    assert STATUS_VALUES == ("ok", "needs_auth", "not_found", "escalate", "error")
