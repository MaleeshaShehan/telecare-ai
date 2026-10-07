"""Subscriber-Account Agent :8002 - the security showcase.   Owner: M3

POST /handle            Envelope -> Envelope   (requires X-Internal-Key)
POST /auth/login        {msisdn, password} -> {otp_sent: true, debug_otp}   rate-limited 5/min
POST /auth/verify-otp   {msisdn, otp} -> {token}
GET  /health

Hard rules: telecare.db opened read-only (mode=ro); subscriber_id comes ONLY
from the verified JWT; all SQL parameterised; bill maths in bill_diff.py.

Today: /handle returns needs_auth when no token, else a stub `ok`.
TODO(M3): verify_jwt -> repository lookups -> bill_diff -> LLM phrasing.
"""
from fastapi import Depends, FastAPI

from shared.audit import log_decision
from shared.envelope import Envelope, make_reply
from shared.http import require_internal_key

app = FastAPI(title="TeleCare Account Agent")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "agent": "account_agent"}


@app.post("/auth/login", dependencies=[Depends(require_internal_key)], status_code=501)
def login_stub(body: dict) -> dict:
    """TODO(builder): see README.md section 2b.
    200 {"otp_sent": true, "channel": "simulated", "debug_otp": "482913", "expires_in": 300}
    200 {"otp_sent": true, "channel": "sms", "expires_in": 300}          (real SMS)
    401 {"detail": "Invalid number or password"}   same message for both failure modes
    429 rate limit 5/minute"""
    return {"detail": "login not implemented yet (Account Agent builder)"}


@app.post("/auth/verify-otp", dependencies=[Depends(require_internal_key)], status_code=501)
def verify_otp_stub(body: dict) -> dict:
    """TODO(builder): see README.md section 2c.
    200 {"token": "<opaque string>", "expires_in": 900}
    401 {"detail": "Code rejected"}   wrong, expired, or 4th attempt"""
    return {"detail": "verify-otp not implemented yet (Account Agent builder)"}


@app.post("/handle", dependencies=[Depends(require_internal_key)])
def handle(env: Envelope) -> Envelope:
    if not env.auth_token:
        log_decision(env.conversation_id, "account_agent", "needs_auth", "no token")
        return make_reply(env, "needs_auth")
    # TODO(M3): subscriber_id = verify_jwt(env.auth_token); None -> needs_auth
    log_decision(env.conversation_id, "account_agent", "stub_answer", f"intent={env.intent.value}")
    return make_reply(env, "ok", {"answer": "[stub] Account Agent would answer from the read-only DB here (M3)."})
