"""Care Orchestrator :8000 - the only service the UI calls.   Owner: M1

Endpoints:
    POST /chat              {conversation_id, message} -> {reply, status, sources, trace}
    POST /auth/login        {conversation_id, msisdn}            requests OTP from Account Agent
    POST /auth/verify-otp   {conversation_id, msisdn, otp}       proxied; token kept server-side
    POST /auth/logout       {conversation_id}
    GET  /auth/status       ?conversation_id=  -> {logged_in}
    GET  /health

Rate limits (step 1 of the decision loop): 20 chat messages per minute per
conversation (X-Conversation-Id header) and 60 per minute per IP address.
"""
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from shared.audit import log_decision
from shared.config import settings
from shared.http import INTERNAL_KEY_HEADER

from agents.orchestrator import composer, session
from agents.orchestrator.router import handle_message

# ---------------------------------------------------------------- rate limit

def conversation_key(request: Request) -> str:
    """Limit per conversation when the UI sends the header, else per IP."""
    return request.headers.get("X-Conversation-Id") or get_remote_address(request)


limiter = Limiter(key_func=get_remote_address)


def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    cid = request.headers.get("X-Conversation-Id", "unknown")
    log_decision(cid, "orchestrator", "rate_limited", str(exc.detail))
    return JSONResponse(status_code=429,
                        content={"reply": composer.SLOW_DOWN, "status": "error", "sources": [], "trace": []})


app = FastAPI(title="TeleCare Orchestrator")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

# ---------------------------------------------------------------- models

class ChatRequest(BaseModel):
    conversation_id: str
    message: str


class LoginRequest(BaseModel):
    conversation_id: str
    msisdn: str


class OtpRequest(BaseModel):
    conversation_id: str
    msisdn: str
    otp: str


class ConversationRef(BaseModel):
    conversation_id: str

# ---------------------------------------------------------------- endpoints

@app.get("/health")
def health() -> dict:
    return {"status": "ok", "agent": "orchestrator"}


@app.post("/chat")
@limiter.limit("20/minute", key_func=conversation_key)
@limiter.limit("60/minute")
def chat(request: Request, req: ChatRequest) -> dict:
    return handle_message(req.conversation_id, req.message)


def _proxy_account(path: str, body: dict) -> tuple[int, dict]:
    """Forward an auth request to the Account Agent with the internal key."""
    url = f"{settings.agent_url('account_agent')}{path}"
    try:
        r = httpx.post(url, json=body, headers={INTERNAL_KEY_HEADER: settings.internal_api_key}, timeout=10.0)
        try:
            data = r.json()
        except ValueError:
            data = {"detail": r.text}
        return r.status_code, data
    except httpx.HTTPError as exc:
        return 503, {"detail": f"account agent unreachable: {exc}"}


@app.post("/auth/login")
def login(req: LoginRequest) -> JSONResponse:
    code, data = _proxy_account("/auth/login", {"msisdn": req.msisdn})
    log_decision(req.conversation_id, "orchestrator", "login_proxied", f"http={code}")
    return JSONResponse(status_code=code, content=data)


@app.post("/auth/verify-otp")
def verify_otp(req: OtpRequest) -> JSONResponse:
    code, data = _proxy_account("/auth/verify-otp", {"msisdn": req.msisdn, "otp": req.otp})
    if code == 200 and data.get("token"):
        # The JWT stays in the orchestrator's session. The browser never sees it.
        session.set_token(req.conversation_id, data["token"])
        log_decision(req.conversation_id, "orchestrator", "otp_verified", "token stored in session")
        return JSONResponse(status_code=200, content={"logged_in": True})
    log_decision(req.conversation_id, "orchestrator", "otp_rejected", f"http={code}")
    return JSONResponse(status_code=code, content={"logged_in": False, **data})


@app.post("/auth/logout")
def logout(req: ConversationRef) -> dict:
    session.set_token(req.conversation_id, None)
    log_decision(req.conversation_id, "orchestrator", "logout", "token cleared")
    return {"logged_in": False}


@app.get("/auth/status")
def auth_status(conversation_id: str) -> dict:
    return {"logged_in": session.get_token(conversation_id) is not None}


# ------------------------------------------------------------ UI support

@app.get("/agents/health")
def agents_health() -> dict:
    """The browser only ever talks to the Orchestrator, so we poll the
    specialists on its behalf for the status pills."""
    result = {"orchestrator": True}
    for name in ("knowledge_agent", "account_agent", "supervisor_agent"):
        try:
            result[name] = httpx.get(f"{settings.agent_url(name)}/health", timeout=1.5).status_code == 200
        except httpx.HTTPError:
            result[name] = False
    return result


@app.get("/tickets")
def tickets() -> list:
    """Open tickets for the human agent console, proxied from the Supervisor."""
    try:
        r = httpx.get(f"{settings.agent_url('supervisor_agent')}/tickets",
                      headers={INTERNAL_KEY_HEADER: settings.internal_api_key}, timeout=5.0)
        return r.json() if r.status_code == 200 else []
    except (httpx.HTTPError, ValueError):
        return []


# Serve the single-page UI from ui/web at "/". Mounted last so API routes win.
_WEB_DIR = Path(__file__).resolve().parents[2] / "ui" / "web"
if _WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="ui")
