"""Subscriber-Account Agent :8002 - the security showcase.   Owner: M3

POST /handle            Envelope -> Envelope   (requires X-Internal-Key)
POST /auth/login        {msisdn} -> {otp_sent: true, channel}   rate-limited 5/min
POST /auth/verify-otp   {msisdn, otp} -> {token}
GET  /health

Hard rules: telecare.db opened read-only (mode=ro); subscriber_id comes ONLY
from the verified JWT; all SQL parameterised; bill maths in bill_diff.py.

Authentication is real; bill and quota lookup remain the next implementation slice.
"""
from collections import defaultdict, deque
from threading import Lock
from time import monotonic
from decimal import Decimal

import sqlite3
import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from shared.audit import log_decision
from shared.envelope import Envelope, make_reply
from shared.http import require_internal_key
from shared.intents import Intent

from agents.account_agent import auth, repository
from agents.account_agent.bill_diff import diff as bill_difference

app = FastAPI(title="TeleCare Account Agent")


class LoginBody(BaseModel):
    msisdn: str


class VerifyOtpBody(BaseModel):
    msisdn: str
    otp: str


_RATE_WINDOW_SECONDS = 60.0
_RATE_MAX = 5
_rate_events: dict[str, deque[float]] = defaultdict(deque)
_rate_lock = Lock()


def _check_rate_limit(*keys: str) -> None:
    now = monotonic()
    with _rate_lock:
        for key in keys:
            events = _rate_events[key]
            while events and now - events[0] >= _RATE_WINDOW_SECONDS:
                events.popleft()
            if len(events) >= _RATE_MAX:
                raise HTTPException(status_code=429, detail="Too many attempts, try again in a minute")
        for key in keys:
            _rate_events[key].append(now)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "agent": "account_agent"}


@app.post("/auth/login", dependencies=[Depends(require_internal_key)])
def login(request: Request, body: LoginBody) -> dict:
    """Request an OTP using only the subscriber's mobile number."""
    msisdn = auth.normalize_msisdn(body.msisdn)
    if not msisdn:
        raise HTTPException(status_code=400, detail="Enter a valid Sri Lankan mobile number")
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(f"ip:{client_ip}", f"msisdn:{msisdn}")

    try:
        subscriber = repository.find_subscriber_by_msisdn(msisdn)
    except (sqlite3.Error, httpx.HTTPError, RuntimeError):
        raise HTTPException(status_code=503, detail="Account service is not ready")

    # Do not reveal whether a number exists in the subscriber database.
    if not subscriber or subscriber.get("account_status", "active") != "active":
        log_decision("auth", "account_agent", "otp_not_sent", "subscriber not found")
        return {"otp_sent": True, "channel": "sms", "expires_in": auth.settings.otp_ttl_seconds}

    try:
        code = auth.create_otp(msisdn, subscriber["subscriber_id"])
    except (sqlite3.Error, httpx.HTTPError, RuntimeError):
        raise HTTPException(status_code=503, detail="Account service is not ready")
    try:
        channel, debug_code = auth.deliver_otp(msisdn, code)
    except auth.SmsDeliveryError:
        auth.invalidate_otp(msisdn)
        log_decision("auth", "account_agent", "sms_failed", "gateway unavailable")
        raise HTTPException(status_code=503, detail="Could not send the verification code. Try again shortly.")

    log_decision("auth", "account_agent", "otp_sent", f"channel={channel}")
    result = {"otp_sent": True, "channel": channel, "expires_in": auth.settings.otp_ttl_seconds}
    if debug_code is not None:
        result["debug_otp"] = debug_code
    return result


@app.post("/auth/verify-otp", dependencies=[Depends(require_internal_key)])
def verify_otp(request: Request, body: VerifyOtpBody) -> dict:
    msisdn = auth.normalize_msisdn(body.msisdn)
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(f"verify-ip:{client_ip}", f"verify-msisdn:{msisdn or body.msisdn}")
    if not msisdn:
        raise HTTPException(status_code=401, detail="Code rejected")
    subscriber_id = auth.verify_otp(msisdn, body.otp)
    if not subscriber_id:
        log_decision("auth", "account_agent", "otp_rejected", "invalid, expired, or exhausted")
        raise HTTPException(status_code=401, detail="Code rejected")
    token = auth.issue_token(subscriber_id)
    log_decision("auth", "account_agent", "otp_verified", "JWT issued")
    return {"token": token, "expires_in": auth.settings.jwt_ttl_minutes * 60}


@app.post("/handle", dependencies=[Depends(require_internal_key)])
def handle(env: Envelope) -> Envelope:
    if not env.auth_token:
        log_decision(env.conversation_id, "account_agent", "needs_auth", "no token")
        return make_reply(env, "needs_auth")
    subscriber_id = auth.verify_token(env.auth_token)
    if not subscriber_id:
        log_decision(env.conversation_id, "account_agent", "needs_auth", "invalid or expired token")
        return make_reply(env, "needs_auth")
    try:
        if not repository.subscriber_exists(subscriber_id):
            log_decision(env.conversation_id, "account_agent", "needs_auth", "unknown subscriber")
            return make_reply(env, "needs_auth")

        if env.intent == Intent.BILL_ENQUIRY:
            return _handle_bill(env, subscriber_id)
        if env.intent == Intent.QUOTA_CHECK:
            return _handle_quota(env, subscriber_id)
    except (sqlite3.Error, repository.RepositoryError):
        log_decision(env.conversation_id, "account_agent", "db_error", "account store unavailable")
        return make_reply(env, "error", {"reason": "Account information is temporarily unavailable"})

    return make_reply(env, "error", {"reason": "Unsupported account request"})


def _money(value: object) -> str:
    amount = Decimal(str(value or 0)).quantize(Decimal("0.01"))
    return f"{amount:,.2f}"


def _handle_bill(env: Envelope, subscriber_id: str) -> Envelope:
    bills = repository.get_bills(subscriber_id, limit=2)
    if len(bills) < 2:
        return make_reply(env, "not_found", {"reason": "Two billing periods are not available"})

    current, previous = bills[0], bills[1]
    current_items = repository.get_bill_items(subscriber_id, current["bill_id"])
    previous_items = repository.get_bill_items(subscriber_id, previous["bill_id"])
    comparison = bill_difference(current, previous, current_items, previous_items)
    change = Decimal(str(comparison["change"]))

    if change > 0:
        direction = f"went up by LKR {_money(change)}"
    elif change < 0:
        direction = f"went down by LKR {_money(abs(change))}"
    else:
        direction = "did not change"

    drivers = comparison["drivers"]
    if drivers:
        lead = drivers[0]
        explanation = f" The largest change was {lead['item']} (LKR {_money(lead['amount'])})."
    else:
        explanation = ""
    plan_note = (
        " Your base-plan charge changed."
        if comparison["base_plan_changed"]
        else " Your base-plan charge was unchanged."
    )
    answer = f"Your latest bill {direction} compared with the previous bill.{explanation}{plan_note}"
    log_decision(env.conversation_id, "account_agent", "bill_compared", "two subscriber bills compared")
    return make_reply(env, "ok", {"answer": answer, "bill_diff": comparison})


def _handle_quota(env: Envelope, subscriber_id: str) -> Envelope:
    usage = repository.get_usage(subscriber_id)
    plan = repository.get_plan(subscriber_id)
    if not usage or not plan:
        return make_reply(env, "not_found", {"reason": "Current usage or plan was not found"})

    if "data_used_mb" in usage:
        used_gb = Decimal(str(usage["data_used_mb"])) / Decimal("1024")
        allowance_gb = Decimal(str(plan["data_quota_mb"])) / Decimal("1024")
        period = str(usage["period_start"])[:7]
    else:
        used_gb = Decimal(str(usage["data_used_gb"]))
        allowance_gb = Decimal(str(plan["data_gb"]))
        period = str(usage["period"])

    used = round(float(used_gb), 2)
    allowance = round(float(allowance_gb), 2)
    remaining = max(round(allowance - used, 2), 0)
    answer = (
        f"You have used {used:.2f} GB of your {allowance:.2f} GB allowance "
        f"for {period}. {remaining:.2f} GB remains."
    )
    quota = {"used_gb": used, "allowance_gb": allowance, "period": period}
    log_decision(env.conversation_id, "account_agent", "quota_returned", "subscriber usage calculated")
    return make_reply(env, "ok", {"answer": answer, "quota": quota})
