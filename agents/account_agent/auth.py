"""OTP authentication and JWTs for the Account Agent.

The phone number identifies an existing synthetic subscriber. A six-digit OTP
is generated here, stored only as a bcrypt hash in the writable auth database,
and delivered by the configured SMS adapter. Successful verification consumes
the OTP and returns the subscriber ID used as the JWT subject.
"""
from __future__ import annotations

import re
import secrets
import sqlite3
import time
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import httpx
import jwt

from shared.config import settings


AUTH_DB = Path(__file__).resolve().parents[2] / "data" / "db" / "auth.db"
MAX_OTP_ATTEMPTS = 3
MSISDN_RE = re.compile(r"^07\d{8}$")
_WEAK_JWT_SECRETS = {"", "dev-only-change-me", "change-me", "secret"}


class SmsDeliveryError(RuntimeError):
    """The configured SMS service did not accept the message."""


def normalize_msisdn(value: str) -> str | None:
    """Normalize a Sri Lankan mobile number to the local 07XXXXXXXX form."""
    compact = re.sub(r"[\s()-]", "", value or "")
    if compact.startswith("+94"):
        compact = "0" + compact[3:]
    elif compact.startswith("94") and len(compact) == 11:
        compact = "0" + compact[2:]
    return compact if MSISDN_RE.fullmatch(compact) else None


def _create_local_otp_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS otp_challenges (
            msisdn_hash TEXT PRIMARY KEY,
            subscriber_id TEXT NOT NULL,
            otp_hash BLOB NOT NULL,
            expires_at INTEGER NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0
        )
        """
    )


def _connect_auth() -> sqlite3.Connection:
    AUTH_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(AUTH_DB, timeout=5)
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(otp_challenges)").fetchall()
    }
    if columns and "msisdn_hash" not in columns:
        # OTP challenges are short-lived. Dropping legacy rows avoids retaining
        # plaintext phone numbers and safely invalidates any outstanding code.
        conn.execute("DROP TABLE otp_challenges")
    _create_local_otp_schema(conn)
    conn.execute("DELETE FROM otp_challenges WHERE expires_at < ?", (int(time.time()),))
    conn.commit()
    return conn


def _using_supabase() -> bool:
    return settings.account_db_backend.strip().lower() == "supabase"


def _jwt_secret_is_strong(secret: str | None = None) -> bool:
    value = (settings.jwt_secret if secret is None else secret).strip()
    return len(value.encode("utf-8")) >= 32 and value.lower() not in _WEAK_JWT_SECRETS


def validate_security_config() -> None:
    """Fail startup when authentication or SMS configuration is unsafe."""
    if not _jwt_secret_is_strong():
        raise RuntimeError("JWT_SECRET must be a non-default random value of at least 32 bytes")
    environment = settings.app_env.strip().lower()
    if environment in {"production", "prod"} and settings.sms_provider.strip().lower() == "simulated":
        raise RuntimeError("SMS_PROVIDER=simulated is not allowed in production")


def _otp_lookup_key() -> bytes:
    configured = settings.otp_lookup_secret.strip()
    if configured:
        return configured.encode("utf-8")
    if not _jwt_secret_is_strong():
        raise RuntimeError("A strong JWT_SECRET is required for OTP lookup protection")
    return hmac.new(
        settings.jwt_secret.encode("utf-8"),
        b"telecare-otp-msisdn-lookup-v1",
        hashlib.sha256,
    ).digest()


def _msisdn_hash(msisdn: str) -> str:
    """Stable, non-reversible lookup key; the raw number is never stored in OTP rows."""
    return hmac.new(
        _otp_lookup_key(),
        msisdn.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def equalize_unknown_login_cost() -> None:
    """Approximate the password-hash work performed for a registered number."""
    bcrypt.hashpw(secrets.token_bytes(16), bcrypt.gensalt())


def _otp_request(
    method: str,
    *,
    params: dict[str, str] | None = None,
    payload: dict | list | None = None,
    prefer: str | None = None,
) -> httpx.Response:
    if not settings.supabase_url or not settings.supabase_key:
        raise RuntimeError("Supabase OTP storage is not configured")
    headers = {
        "apikey": settings.supabase_key,
        "Authorization": f"Bearer {settings.supabase_key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    response = httpx.request(
        method,
        f"{settings.supabase_url.rstrip('/')}/rest/v1/otp_challenges",
        params=params,
        json=payload,
        headers=headers,
        timeout=10.0,
    )
    response.raise_for_status()
    return response


def _create_supabase_otp(msisdn: str, subscriber_id: str, code: str) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.otp_ttl_seconds)
    encoded_hash = bcrypt.hashpw(code.encode("ascii"), bcrypt.gensalt()).decode("ascii")
    _otp_request(
        "POST",
        params={"on_conflict": "msisdn_hash"},
        payload={
            "msisdn_hash": _msisdn_hash(msisdn),
            "subscriber_id": subscriber_id,
            "otp_hash": encoded_hash,
            "attempts_remaining": MAX_OTP_ATTEMPTS,
            "expires_at": expires_at.isoformat(),
            "last_sent_at": datetime.now(timezone.utc).isoformat(),
            "consumed_at": None,
        },
        prefer="resolution=merge-duplicates,return=minimal",
    )


def _invalidate_supabase_otp(msisdn: str) -> None:
    _otp_request(
        "DELETE",
        params={"msisdn_hash": f"eq.{_msisdn_hash(msisdn)}"},
        prefer="return=minimal",
    )


def _verify_supabase_otp(msisdn: str, code: str) -> str | None:
    key = _msisdn_hash(msisdn)
    response = _otp_request(
        "GET",
        params={
            "select": "subscriber_id,otp_hash,expires_at,attempts_remaining",
            "msisdn_hash": f"eq.{key}",
            "limit": "1",
        },
    )
    rows = response.json()
    if not rows:
        return None
    row = rows[0]
    expires_at = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
    attempts_remaining = int(row["attempts_remaining"])
    if expires_at <= datetime.now(timezone.utc) or attempts_remaining <= 0:
        _invalidate_supabase_otp(msisdn)
        return None
    valid = bool(re.fullmatch(r"\d{6}", code or "")) and bcrypt.checkpw(
        code.encode("ascii"), str(row["otp_hash"]).encode("ascii")
    )
    if not valid:
        remaining = attempts_remaining - 1
        if remaining <= 0:
            _invalidate_supabase_otp(msisdn)
        else:
            _otp_request(
                "PATCH",
                params={"msisdn_hash": f"eq.{key}"},
                payload={"attempts_remaining": remaining},
                prefer="return=minimal",
            )
        return None
    _invalidate_supabase_otp(msisdn)
    return str(row["subscriber_id"])


def create_otp(msisdn: str, subscriber_id: str) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    if _using_supabase():
        _create_supabase_otp(msisdn, subscriber_id, code)
        return code
    otp_hash = bcrypt.hashpw(code.encode("ascii"), bcrypt.gensalt())
    expires_at = int(time.time()) + settings.otp_ttl_seconds
    with _connect_auth() as conn:
        conn.execute(
            """
            INSERT INTO otp_challenges (msisdn_hash, subscriber_id, otp_hash, expires_at, attempts)
            VALUES (?, ?, ?, ?, 0)
            ON CONFLICT(msisdn_hash) DO UPDATE SET
                subscriber_id = excluded.subscriber_id,
                otp_hash = excluded.otp_hash,
                expires_at = excluded.expires_at,
                attempts = 0
            """,
            (_msisdn_hash(msisdn), subscriber_id, otp_hash, expires_at),
        )
    return code


def invalidate_otp(msisdn: str) -> None:
    if _using_supabase():
        _invalidate_supabase_otp(msisdn)
        return
    with _connect_auth() as conn:
        conn.execute("DELETE FROM otp_challenges WHERE msisdn_hash = ?", (_msisdn_hash(msisdn),))


def verify_otp(msisdn: str, code: str) -> str | None:
    """Consume a valid OTP and return its subscriber ID."""
    if _using_supabase():
        return _verify_supabase_otp(msisdn, code)
    with _connect_auth() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT subscriber_id, otp_hash, expires_at, attempts FROM otp_challenges WHERE msisdn_hash = ?",
            (_msisdn_hash(msisdn),),
        ).fetchone()
        if not row:
            return None

        subscriber_id, otp_hash, expires_at, attempts = row
        if expires_at < int(time.time()) or attempts >= MAX_OTP_ATTEMPTS:
            conn.execute("DELETE FROM otp_challenges WHERE msisdn_hash = ?", (_msisdn_hash(msisdn),))
            return None

        valid = bool(re.fullmatch(r"\d{6}", code or "")) and bcrypt.checkpw(
            code.encode("ascii"), otp_hash
        )
        if not valid:
            next_attempt = attempts + 1
            if next_attempt >= MAX_OTP_ATTEMPTS:
                conn.execute("DELETE FROM otp_challenges WHERE msisdn_hash = ?", (_msisdn_hash(msisdn),))
            else:
                conn.execute(
                    "UPDATE otp_challenges SET attempts = ? WHERE msisdn_hash = ?",
                    (next_attempt, _msisdn_hash(msisdn)),
                )
            return None

        conn.execute("DELETE FROM otp_challenges WHERE msisdn_hash = ?", (_msisdn_hash(msisdn),))
        return str(subscriber_id)


def issue_token(subscriber_id: str) -> str:
    if not _jwt_secret_is_strong():
        raise RuntimeError("JWT signing is unavailable because JWT_SECRET is unsafe")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subscriber_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_ttl_minutes),
        "type": "account_access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def verify_token(token: str) -> str | None:
    if not _jwt_secret_is_strong():
        return None
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("type") != "account_access":
            return None
        subscriber_id = payload.get("sub")
        return str(subscriber_id) if subscriber_id else None
    except jwt.PyJWTError:
        return None


def send_sms(msisdn: str, message: str) -> bool:
    """Send through the configurable local HTTP gateway.

    Default JSON: {"to": "071...", "message": "...", "sender_id": "TeleCare"}.
    Field names and the authentication header can be changed in .env.
    """
    url = settings.sms_gateway_url.strip()
    if not url:
        return False

    payload = {
        settings.sms_gateway_recipient_field: msisdn,
        settings.sms_gateway_message_field: message,
    }
    if settings.sms_gateway_sender_field:
        payload[settings.sms_gateway_sender_field] = settings.sms_sender_id

    headers: dict[str, str] = {}
    if settings.sms_gateway_key:
        value = settings.sms_gateway_key
        if settings.sms_gateway_auth_header.lower() == "authorization" and not value.lower().startswith("bearer "):
            value = f"Bearer {value}"
        headers[settings.sms_gateway_auth_header] = value

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=5.0)
        response.raise_for_status()
        return True
    except httpx.HTTPError:
        return False


def _textit_number(msisdn: str) -> str:
    """Convert local 07XXXXXXXX numbers to Textit.biz's 947XXXXXXXX form."""
    return f"94{msisdn[1:]}" if msisdn.startswith("0") else msisdn.lstrip("+")


def send_textit_sms(msisdn: str, message: str) -> bool:
    """Deliver one SMS through the Textit.biz REST v1 API."""
    url = settings.sms_gateway_url.strip() or "https://api.textit.biz/"
    api_key = settings.sms_gateway_key.strip()
    if not api_key:
        return False
    headers = {
        "Authorization": f"Basic {api_key}",
        "X-API-VERSION": "v1",
        "Accept": "*/*",
    }
    payload = {"to": _textit_number(msisdn), "text": message}
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=10.0)
        response.raise_for_status()
        return True
    except httpx.HTTPError:
        return False


def deliver_otp(msisdn: str, code: str) -> tuple[str, str | None]:
    """Deliver an OTP without ever returning its plaintext to the API caller."""
    provider = settings.sms_provider.lower()
    if provider == "simulated":
        return "simulated", None
    text = f"TeleCare: your one-time code is {code}. It expires in 5 minutes."
    if provider == "textit":
        if not send_textit_sms(msisdn, text):
            raise SmsDeliveryError("Textit.biz gateway unavailable")
        return "sms", None
    if provider != "http":
        raise SmsDeliveryError("unsupported SMS provider")
    if not send_sms(msisdn, text):
        raise SmsDeliveryError("SMS gateway unavailable")
    return "sms", None
