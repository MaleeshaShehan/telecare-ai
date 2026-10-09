"""Care Orchestrator :8000 - the only service the UI calls.   Owner: M1

Endpoints:
    POST /chat              {message} -> {reply, status, sources, trace}
    POST /auth/login        {msisdn}            requests OTP from Account Agent
    POST /auth/verify-otp   {msisdn, otp}       proxied; token kept server-side
    POST /auth/logout       {}
    GET  /auth/status       -> {logged_in}
    GET  /health

Rate limits (step 1 of the decision loop): 20 chat messages per minute per
server-issued session cookie and 60 per minute per IP address.
"""
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from shared.audit import log_decision, rekey_trace
from shared.config import settings
from shared.http import INTERNAL_KEY_HEADER

from agents.orchestrator import composer, session
from agents.orchestrator.router import handle_message

# ---------------------------------------------------------------- rate limit

def conversation_key(request: Request) -> str:
    """Limit by the server-issued session cookie, else by source IP."""
    return request.cookies.get(session.COOKIE_NAME) or get_remote_address(request)


limiter = Limiter(key_func=get_remote_address)


def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    cid = request.cookies.get(session.COOKIE_NAME, "anonymous")
    log_decision(cid, "orchestrator", "rate_limited", str(exc.detail))
    return JSONResponse(status_code=429,
                        content={"reply": composer.SLOW_DOWN, "status": "error", "sources": [], "trace": []})


app = FastAPI(title="TeleCare Orchestrator")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

# ---------------------------------------------------------------- models

class ChatRequest(BaseModel):
    message: str


class LoginRequest(BaseModel):
    msisdn: str


class OtpRequest(BaseModel):
    msisdn: str
    otp: str


class ConversationRef(BaseModel):
    pass


def _resolve_session(request: Request) -> tuple[str, bool]:
    return session.resolve(request.cookies.get(session.COOKIE_NAME))


def _cookie_secure() -> bool:
    return settings.app_env.strip().lower() in {"production", "prod"}


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key=session.COOKIE_NAME,
        value=session_id,
        max_age=session.ABSOLUTE_TTL_SECONDS,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
    )

# ---------------------------------------------------------------- endpoints

@app.get("/health")
def health() -> dict:
    return {"status": "ok", "agent": "orchestrator"}


@app.post("/chat")
@limiter.limit("20/minute", key_func=conversation_key)
@limiter.limit("60/minute")
def chat(request: Request, response: Response, req: ChatRequest) -> dict:
    session_id, created = _resolve_session(request)
    if created:
        _set_session_cookie(response, session_id)
    return handle_message(session_id, req.message)


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
def login(request: Request, req: LoginRequest) -> JSONResponse:
    session_id, created = _resolve_session(request)
    code, data = _proxy_account("/auth/login", {"msisdn": req.msisdn})
    log_decision(session_id, "orchestrator", "login_proxied", f"http={code}")
    if code == 200:
        # Defense in depth: an Account Agent must never make an OTP available
        # to the browser, even if a stale specialist still returns debug data.
        data = {
            "otp_sent": bool(data.get("otp_sent", True)),
            "channel": "sms",
            "expires_in": int(data.get("expires_in", settings.otp_ttl_seconds)),
        }
    response = JSONResponse(status_code=code, content=data)
    if created:
        _set_session_cookie(response, session_id)
    return response


@app.post("/auth/verify-otp")
def verify_otp(request: Request, req: OtpRequest) -> JSONResponse:
    session_id, created = _resolve_session(request)
    code, data = _proxy_account("/auth/verify-otp", {"msisdn": req.msisdn, "otp": req.otp})
    if code == 200 and data.get("token"):
        # The JWT stays in the orchestrator's session. The browser never sees it.
        rotated_id = session.rotate(session_id)
        rekey_trace(session_id, rotated_id)
        session.set_token(rotated_id, data["token"])
        log_decision(rotated_id, "orchestrator", "otp_verified", "token stored in rotated session")
        response = JSONResponse(status_code=200, content={"logged_in": True})
        _set_session_cookie(response, rotated_id)
        return response
    log_decision(session_id, "orchestrator", "otp_rejected", f"http={code}")
    response = JSONResponse(status_code=code, content={"logged_in": False, **data})
    if created:
        _set_session_cookie(response, session_id)
    return response


@app.post("/auth/logout")
def logout(request: Request, _req: ConversationRef) -> JSONResponse:
    cookie_value = request.cookies.get(session.COOKIE_NAME)
    if cookie_value:
        log_decision(cookie_value, "orchestrator", "logout", "session destroyed")
        session.reset(cookie_value)
    response = JSONResponse(status_code=200, content={"logged_in": False})
    response.delete_cookie(session.COOKIE_NAME, path="/", samesite="strict")
    return response


@app.get("/auth/status")
def auth_status(request: Request) -> JSONResponse:
    session_id, created = _resolve_session(request)
    response = JSONResponse(
        status_code=200,
        content={"logged_in": session.get_token(session_id) is not None},
    )
    if created:
        _set_session_cookie(response, session_id)
    return response


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
