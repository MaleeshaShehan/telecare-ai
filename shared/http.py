"""call_agent(): the one function the orchestrator uses to talk to a specialist.

Adds the X-Internal-Key header, a 60-second timeout (the Knowledge Agent loads
its embedding model on the first call) and one retry, but only when the
connection failed outright. A request that timed out is still running inside
the specialist, so retrying it would just race the original. Specialists use
`require_internal_key` as a FastAPI dependency so a call without the key
gets 401.
"""
import httpx
from fastapi import Header, HTTPException

from shared.config import settings
from shared.envelope import Envelope, make_reply

TIMEOUT_SECONDS = 60.0
INTERNAL_KEY_HEADER = "X-Internal-Key"


def call_agent(env: Envelope) -> Envelope:
    """POST the envelope to env.receiver_agent's /handle and return its reply.

    Network or server failure becomes a reply with status "error" so the
    orchestrator can apologise and offer a human instead of crashing.
    """
    url = f"{settings.agent_url(env.receiver_agent)}/handle"
    headers = {INTERNAL_KEY_HEADER: settings.internal_api_key}
    body = env.model_dump(mode="json")

    last_error: Exception | None = None
    for _attempt in range(2):  # one try + at most one retry
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                resp = client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            return Envelope.model_validate(resp.json())
        except httpx.ConnectError as exc:
            last_error = exc          # agent not up yet: worth one retry
            continue
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc          # timeout, 5xx or bad body: do not duplicate the request
            break
    return make_reply(env, "error", {"reason": f"{env.receiver_agent} unreachable: {type(last_error).__name__}"})


def require_internal_key(x_internal_key: str = Header(default="")) -> None:
    """FastAPI dependency: reject any specialist call without the shared key."""
    if x_internal_key != settings.internal_api_key:
        raise HTTPException(status_code=401, detail="missing or invalid internal key")
