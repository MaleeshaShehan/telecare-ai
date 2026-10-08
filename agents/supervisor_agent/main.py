"""Care Supervisor Agent :8003 - human in the loop.   Owner: M4

POST /handle  Envelope with payload.task = "assess" | "escalate"   (requires X-Internal-Key)
GET  /health
GET  /tickets

assess   -> {status: ok, sentiment, score, escalate: bool, reason, priority}
escalate -> {status: escalate, ticket_id, priority, answer}
"""
from fastapi import Depends, FastAPI

from shared.audit import log_decision
from shared.envelope import Envelope, make_reply
from shared.http import require_internal_key

from .sentiment import assess
from .summarizer import summarize
from .tickets import create_ticket, list_open_tickets

app = FastAPI(title="TeleCare Supervisor Agent")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "agent": "supervisor_agent"}


@app.get("/tickets", dependencies=[Depends(require_internal_key)])
def list_tickets() -> list:
    """Return open tickets for the human agent console."""
    return list_open_tickets()


@app.post("/handle", dependencies=[Depends(require_internal_key)])
def handle(env: Envelope) -> Envelope:
    task = env.payload.get("task", "assess")

    # ---------- ASSESS ----------
    if task == "assess":
        result = assess(
            message=env.payload.get("message", ""),
            intent=env.payload.get("intent", ""),
            failed_count=env.payload.get("failed_count", 0),
        )
        log_decision(env.conversation_id, "supervisor_agent", "assess", result["reason"])
        return make_reply(env, "ok", result)

    # ---------- ESCALATE ----------
    if task == "escalate":
        history = env.payload.get("history", [])
        reason = env.payload.get("reason", "unknown")
        priority = env.payload.get("priority", "normal")

        # 1. Summarize the conversation (PII masked inside summarizer)
        summary = summarize(history)

        # 2. Create the ticket (sequential ID from tickets.py)
        ticket_id = create_ticket(env.conversation_id, summary, priority)

        # 3. Audit log the decision
        log_decision(env.conversation_id, "supervisor_agent", "escalate", reason)

        # 4. Return the reply with ticket ID and 24-hour promise
        return make_reply(env, "escalate", {
            "ticket_id": ticket_id,
            "priority": priority,
            "answer": (
                f"I'm sorry about the trouble. I've created ticket {ticket_id} "
                f"with your full case details; a human agent will contact you within 24 hours."
            ),
        })

    # ---------- UNKNOWN TASK ----------
    return make_reply(env, "error", {"message": f"Unknown task: {task}"})