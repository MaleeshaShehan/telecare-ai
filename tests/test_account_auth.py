"""Passwordless Account Agent authentication."""
import time

import jwt

from agents.account_agent import auth


def test_msisdn_normalization():
    assert auth.normalize_msisdn("0712345678") == "0712345678"
    assert auth.normalize_msisdn("+94 71 234 5678") == "0712345678"
    assert auth.normalize_msisdn("123") is None


def test_otp_is_hashed_consumed_and_limited(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_DB", tmp_path / "auth.db")
    code = auth.create_otp("0712345678", "SUB-0001")
    assert len(code) == 6 and code.isdigit()
    raw = (tmp_path / "auth.db").read_bytes()
    assert code.encode() not in raw
    assert auth.verify_otp("0712345678", code) == "SUB-0001"
    assert auth.verify_otp("0712345678", code) is None

    code = auth.create_otp("0712345678", "SUB-0001")
    assert auth.verify_otp("0712345678", "000000") is None
    assert auth.verify_otp("0712345678", "000001") is None
    assert auth.verify_otp("0712345678", "000002") is None
    assert auth.verify_otp("0712345678", code) is None


def test_expired_otp_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_DB", tmp_path / "auth.db")
    code = auth.create_otp("0712345678", "SUB-0001")
    with auth._connect_auth() as conn:
        conn.execute("UPDATE otp_challenges SET expires_at = ?", (int(time.time()) - 1,))
    assert auth.verify_otp("0712345678", code) is None


def test_jwt_round_trip_and_tamper(monkeypatch):
    test_secret = "test-secret-that-is-definitely-longer-than-32-bytes"
    monkeypatch.setattr(auth.settings, "jwt_secret", test_secret)
    token = auth.issue_token("SUB-0001")
    assert auth.verify_token(token) == "SUB-0001"
    assert auth.verify_token(token[:-1] + ("a" if token[-1] != "a" else "b")) is None
    wrong_type = jwt.encode({"sub": "SUB-0001", "type": "other"}, test_secret, algorithm="HS256")
    assert auth.verify_token(wrong_type) is None


def test_real_sms_uses_configurable_gateway(monkeypatch):
    seen = {}

    class Response:
        def raise_for_status(self):
            return None

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return Response()

    monkeypatch.setattr(auth.settings, "sms_gateway_url", "http://127.0.0.1:8787/send")
    monkeypatch.setattr(auth.settings, "sms_gateway_key", "secret")
    monkeypatch.setattr(auth.httpx, "post", fake_post)
    assert auth.send_sms("0712345678", "code 123456") is True
    assert seen["json"][auth.settings.sms_gateway_recipient_field] == "0712345678"
    assert seen["json"][auth.settings.sms_gateway_message_field] == "code 123456"
    assert seen["headers"][auth.settings.sms_gateway_auth_header] == "Bearer secret"


def test_textit_sms_contract(monkeypatch):
    seen = {}

    class Response:
        def raise_for_status(self):
            return None

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return Response()

    monkeypatch.setattr(auth.settings, "sms_gateway_url", "https://api.textit.biz/")
    monkeypatch.setattr(auth.settings, "sms_gateway_key", "api-key")
    monkeypatch.setattr(auth.httpx, "post", fake_post)
    assert auth.send_textit_sms("0712345678", "OTP 123456") is True
    assert seen["url"] == "https://api.textit.biz/"
    assert seen["json"] == {"to": "94712345678", "text": "OTP 123456"}
    assert seen["headers"]["Authorization"] == "Basic api-key"
    assert seen["headers"]["X-API-VERSION"] == "v1"


def test_textit_delivery_never_exposes_code(monkeypatch):
    monkeypatch.setattr(auth.settings, "sms_provider", "textit")
    monkeypatch.setattr(auth, "send_textit_sms", lambda msisdn, message: True)
    assert auth.deliver_otp("0712345678", "123456") == ("sms", None)
