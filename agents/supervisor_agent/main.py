"""Care Supervisor Agent :8003 - human in the loop.   Owner: M4

POST /handle  Envelope with payload.task = "assess" | "escalate"   (requires X-Internal-Key)
GET  /health

assess   -> {status: ok, sentiment, score, escalate: bool, reason, priority}
escalate -> {status: escalate, ticket_id, answer}

Today: assess returns neutral / no escalation; escalate returns a fixed ticket.
TODO(M4): sentiment.py (VADER + rules), summarizer.py (LLM JSON), tickets.py (tickets.db).
"""
from fastapi import Depends, FastAPI

from shared.audit import log_decision
from shared.envelope import Envelope, make_reply
from shared.http import require_internal_key

app = FastAPI(title="TeleCare Supervisor Agent")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "agent": "supervisor_agent"}


@app.get("/tickets", dependencies=[Depends(require_internal_key)])
def list_tickets() -> list:
    """TODO(M4): return tickets.list_open_tickets(). Shape per ticket:
    {ticket_id, created_at, priority, status, issue, customer_mood, conversation_id}"""
    return []


@app.post("/handle", dependencies=[Depends(require_internal_key)])
def handle(env: Envelope) -> Envelope:
    task = env.payload.get("task", "assess")
    if task == "escalate":
        log_decision(env.conversation_id, "supervisor_agent", "escalate", "stub ticket")
        return make_reply(env, "escalate", {
            "ticket_id": "T-1001",
            "answer": "I'm sorry about the trouble. I've created ticket T-1001 with your case details; "
                      "a human agent will contact you within 24 hours.",
        })
    log_decision(env.conversation_id, "supervisor_agent", "assess", "stub neutral")
    return make_reply(env, "ok", {"sentiment": "neutral", "score": 0.0, "escalate": False,
                                  "reason": "stub", "priority": "normal"})
