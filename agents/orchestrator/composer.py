"""Turns a decision or a specialist reply into the final response for the UI.   Owner: M1

Response shape the UI expects:
    {"reply": str, "status": str, "sources": list, "trace": list}

Every reply passes through finish(), which adds the AI disclosure on the
first turn, records the assistant turn in the session, updates the
failed-answer counter and attaches the audit trace.
"""
from shared.audit import get_trace, log_decision
from shared.envelope import Envelope
from shared.security import contains_prompt_leak, register_system_prompt

from agents.orchestrator import session

# Output guard: register every system prompt the agents use so a reply that quotes
# one is caught before it reaches the user. Imports are best-effort so a missing
# agent module never breaks the Orchestrator.
def _register_known_prompts() -> None:
    try:
        from agents.orchestrator.nlu import NLU_SYSTEM
        register_system_prompt(NLU_SYSTEM)
    except Exception:
        pass
    for mod, names in (("agents.knowledge_agent.prompts", ("GROUNDED_SYSTEM", "PLAN_ADVICE_SYSTEM", "QUERY_REWRITE_SYSTEM")),
                       ("agents.account_agent.prompts", ("BILL_EXPLAIN_SYSTEM",))):
        try:
            m = __import__(mod, fromlist=list(names))
            for n in names:
                register_system_prompt(getattr(m, n, ""))
        except Exception:
            pass


_register_known_prompts()
LEAK_REFUSAL = "I can't share that. Is there something about your plan, roaming, coverage or bill I can help with?"

AI_DISCLOSURE = "Hi, I'm TeleCare's AI assistant. "

REFUSAL_INJECTION = "I can only help with telecom questions about packages, roaming, coverage, your bill or your data."
REFUSAL_OUT_OF_SCOPE = "Sorry, that is outside what I can help with. I handle telecom questions only."
CLARIFY = "Could you tell me a little more? For example, is this about a package, roaming, coverage, or your bill?"
NEEDS_AUTH = "To look at your account I need you to log in first. Please use the login panel on the left."
ACCOUNT_PRIVACY_REFUSAL = (
    "I can only provide account details for the mobile number you verified when you logged in. "
    "I can't access or disclose details for another number."
)
NOT_FOUND = "I don't have that information in our documents. Would you like me to connect you to a human agent?"
ERROR = "Sorry, something went wrong on my side. Would you like me to connect you to a human agent?"
SLOW_DOWN = "You're sending messages very quickly. Please slow down and try again in a moment."


def finish(conversation_id: str, reply: str, status: str, sources: list | None = None,
           extra: dict | None = None) -> dict:
    """`extra` carries structured data the UI renders as cards, e.g.
    bill_diff from the Account Agent or ticket_id from the Supervisor."""
    state = session.get(conversation_id)
    if contains_prompt_leak(reply):
        log_decision(conversation_id, "orchestrator", "prompt_leak_blocked", "reply quoted a system prompt")
        reply, sources, extra = LEAK_REFUSAL, [], {}
    if not state["disclosed"]:
        reply = AI_DISCLOSURE + reply
        state["disclosed"] = True
        log_decision(conversation_id, "orchestrator", "ai_disclosure_shown", "first turn")
    session.add_turn(conversation_id, "assistant", reply)
    session.record_outcome(conversation_id, status)
    return {"reply": reply, "status": status, "sources": sources or [], "extra": extra or {},
            "trace": get_trace(conversation_id)}


_NOT_EXTRA = {"status", "answer", "sources", "reason"}


def compose(conversation_id: str, reply: Envelope) -> dict:
    """Map a specialist's reply envelope to the UI response."""
    status = reply.payload.get("status", "error")
    log_decision(conversation_id, "orchestrator", f"result={status}", f"from={reply.sender_agent}")
    extra = {k: v for k, v in reply.payload.items() if k not in _NOT_EXTRA}

    if status == "ok":
        return finish(conversation_id, reply.payload.get("answer", ""), "ok", reply.payload.get("sources", []), extra)
    if status == "needs_auth":
        return finish(conversation_id, NEEDS_AUTH, "needs_auth")
    if status == "forbidden":
        return finish(conversation_id, ACCOUNT_PRIVACY_REFUSAL, "forbidden")
    if status == "not_found":
        return finish(conversation_id, NOT_FOUND, "not_found")
    if status == "escalate":
        return finish(conversation_id, reply.payload.get("answer", "I've passed this to a human agent."), "escalate",
                      None, extra)
    return finish(conversation_id, ERROR, "error")
