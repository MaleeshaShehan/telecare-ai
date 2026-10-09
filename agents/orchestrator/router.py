"""The per-message decision loop (BUILD_PLAN section 5).   Owner: M1

Each numbered step can end the turn early. That is what makes the
orchestrator an agent rather than a pipe. Step 1 (rate limit) lives in
main.py because it wraps the HTTP endpoint.

 2. Sanitize            strip HTML / control chars, cap at 1,000 chars
 3. Injection check     blocked -> refuse, log, stop
 4. NLU                 intent + entities (LLM, keyword fallback)
 5. Assess              Supervisor says escalate? -> escalate, return ticket, stop
    Clarify             low confidence -> ask one question, stop
 6. Auth gate           intent needs login and no token -> needs_auth, stop
 7. Route               envelope to the owning agent
 8. Handle result       ok / not_found / error / needs_auth / escalate
 9. Compose             disclosure on first turn, sources, audit trace
"""
from shared.audit import log_decision
from shared.envelope import Envelope
from shared.http import call_agent
from shared.intents import AUTH_REQUIRED, INTENT_OWNER, Intent
from shared.security import injection_findings, sanitize

from agents.orchestrator import composer, nlu, session

CONFIDENCE_FLOOR = 0.5


def handle_message(conversation_id: str, raw_message: str) -> dict:
    state = session.get(conversation_id)

    # 2. Sanitize
    message = sanitize(raw_message)
    if not message:
        return composer.finish(conversation_id, composer.CLARIFY, "ok")

    # 3. Injection check (normalised, rule-scored; the rule names explain the refusal)
    finding = injection_findings(message)
    if finding.blocked:
        log_decision(conversation_id, "orchestrator", "injection_blocked",
                     f"score={finding.score:.1f} rules={','.join(finding.rules)}")
        return composer.finish(conversation_id, composer.REFUSAL_INJECTION, "ok")
    if finding.rules:  # suspicious but under the threshold: record it, let it through
        log_decision(conversation_id, "orchestrator", "injection_suspected",
                     f"score={finding.score:.1f} rules={','.join(finding.rules)}")

    session.add_turn(conversation_id, "user", message)

    # 4. NLU
    result = nlu.classify(message)
    intent: Intent = result["intent"]
    log_decision(conversation_id, "orchestrator", f"intent={intent.value}",
                 f"confidence={result['confidence']:.2f} method={result['method']}")

    # 5. Assess (Supervisor). A complaint always escalates, whatever the sentiment.
    assessment = _assess(conversation_id, message, intent, state["failed_count"])
    if assessment.get("escalate") or intent == Intent.COMPLAINT:
        reason = assessment.get("reason") or "intent=complaint"
        return _escalate(conversation_id, reason, assessment.get("priority", "normal"))

    # Clarify instead of guessing
    if result["confidence"] < CONFIDENCE_FLOOR or result["needs_clarification"]:
        log_decision(conversation_id, "orchestrator", "clarify", f"confidence={result['confidence']:.2f}")
        return composer.finish(conversation_id, composer.CLARIFY, "ok")

    # 6. Auth gate
    token = state["token"]
    if intent in AUTH_REQUIRED and not token:
        log_decision(conversation_id, "orchestrator", "auth_required", f"intent={intent.value}")
        return composer.finish(conversation_id, composer.NEEDS_AUTH, "needs_auth")

    # 7. Route
    owner = INTENT_OWNER[intent]
    if owner == "orchestrator":
        log_decision(conversation_id, "orchestrator", "answered_locally", "out_of_scope")
        return composer.finish(conversation_id, composer.REFUSAL_OUT_OF_SCOPE, "ok")

    env = Envelope(
        conversation_id=conversation_id,
        sender_agent="orchestrator",
        receiver_agent=owner,
        intent=intent,
        payload={"query": message, "entities": result["entities"]},
        auth_token=token if owner == "account_agent" else None,
    )
    log_decision(conversation_id, "orchestrator", f"route->{owner}", f"intent={intent.value}")
    reply = call_agent(env)

    # 8 + 9. Handle result and compose
    return composer.compose(conversation_id, reply)


# ------------------------------------------------------------- supervisor

def _assess(conversation_id: str, message: str, intent: Intent, failed_count: int) -> dict:
    """Ask the Supervisor whether this turn needs a human. A Supervisor outage
    never blocks the turn: we log it and carry on without escalation."""
    env = Envelope(
        conversation_id=conversation_id,
        sender_agent="orchestrator",
        receiver_agent="supervisor_agent",
        intent=intent,
        payload={"task": "assess", "message": message, "intent": intent.value, "failed_count": failed_count},
    )
    reply = call_agent(env)
    if reply.payload.get("status") != "ok":
        log_decision(conversation_id, "orchestrator", "assess_unavailable", str(reply.payload.get("reason", "")))
        return {}
    log_decision(conversation_id, "orchestrator", "assess",
                 f"sentiment={reply.payload.get('sentiment')} escalate={reply.payload.get('escalate')}")
    return reply.payload


def _escalate(conversation_id: str, reason: str, priority: str) -> dict:
    """Hand the conversation to the Supervisor for a ticket. The Supervisor
    masks PII before summarising."""
    state = session.get(conversation_id)
    env = Envelope(
        conversation_id=conversation_id,
        sender_agent="orchestrator",
        receiver_agent="supervisor_agent",
        intent=Intent.COMPLAINT,
        payload={"task": "escalate", "history": [dict(t) for t in state["history"]],  # snapshot, not a reference
                 "reason": reason, "priority": priority},
    )
    log_decision(conversation_id, "orchestrator", "escalate", f"{reason} priority={priority}")
    reply = call_agent(env)
    return composer.compose(conversation_id, reply)
