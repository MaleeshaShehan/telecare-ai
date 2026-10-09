"""The message envelope: our defined agent communication protocol.

Every request and reply between agents is one Envelope sent as JSON over HTTP.
Eight fields, never more. Replies reuse the same shape and put `status` plus
the result inside `payload`.

Reply status values: ok | needs_auth | forbidden | not_found | escalate | error
"""
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from shared.intents import Intent

Agent = Literal["orchestrator", "knowledge_agent", "account_agent", "supervisor_agent"]

Status = Literal["ok", "needs_auth", "forbidden", "not_found", "escalate", "error"]
STATUS_VALUES: tuple[str, ...] = (
    "ok",
    "needs_auth",
    "forbidden",
    "not_found",
    "escalate",
    "error",
)


class Envelope(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    conversation_id: str
    sender_agent: Agent
    receiver_agent: Agent
    intent: Intent
    payload: dict
    auth_token: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def make_reply(req: Envelope, status: Status, result: Optional[dict] = None) -> Envelope:
    """Build the reply to `req`: swap sender and receiver, keep the intent and
    conversation, and put `status` plus the result in the payload."""
    return Envelope(
        conversation_id=req.conversation_id,
        sender_agent=req.receiver_agent,
        receiver_agent=req.sender_agent,
        intent=req.intent,
        payload={"status": status, **(result or {})},
        auth_token=None,  # replies never carry the token back
    )
