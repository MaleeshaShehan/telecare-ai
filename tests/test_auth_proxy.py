"""Orchestrator auth endpoints: proxy to the Account Agent, keep the JWT server-side."""
from fastapi.testclient import TestClient

from agents.orchestrator import main, session
from agents.orchestrator.main import app

client = TestClient(app)


def _fake_account(responses: dict):
    """responses: path -> (status_code, json). Records forwarded bodies."""
    seen = {}
    def fake(path, body):
        seen[path] = body
        return responses[path]
    fake.seen = seen
    return fake


def test_login_forwards_only_credentials(monkeypatch, fresh_session):
    fake = _fake_account({"/auth/login": (200, {"otp_sent": True, "debug_otp": "123456"})})
    monkeypatch.setattr(main, "_proxy_account", fake)
    r = client.post("/auth/login", json={"conversation_id": fresh_session, "msisdn": "0712345678", "password": "pw"})
    assert r.status_code == 200
    assert r.json()["debug_otp"] == "123456"
    assert fake.seen["/auth/login"] == {"msisdn": "0712345678", "password": "pw"}


def test_login_failure_passes_status_through(monkeypatch, fresh_session):
    monkeypatch.setattr(main, "_proxy_account", _fake_account({"/auth/login": (401, {"detail": "invalid credentials"})}))
    r = client.post("/auth/login", json={"conversation_id": fresh_session, "msisdn": "0712345678", "password": "bad"})
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid credentials"


def test_verify_otp_stores_token_in_session_not_in_response(monkeypatch, fresh_session):
    monkeypatch.setattr(main, "_proxy_account", _fake_account({"/auth/verify-otp": (200, {"token": "jwt-secret"})}))
    r = client.post("/auth/verify-otp", json={"conversation_id": fresh_session, "msisdn": "0712345678", "otp": "123456"})
    assert r.status_code == 200
    assert r.json() == {"logged_in": True}
    assert "jwt-secret" not in r.text
    assert session.get_token(fresh_session) == "jwt-secret"
    assert client.get("/auth/status", params={"conversation_id": fresh_session}).json()["logged_in"] is True


def test_wrong_otp_leaves_session_logged_out(monkeypatch, fresh_session):
    monkeypatch.setattr(main, "_proxy_account", _fake_account({"/auth/verify-otp": (401, {"detail": "wrong code"})}))
    r = client.post("/auth/verify-otp", json={"conversation_id": fresh_session, "msisdn": "0712345678", "otp": "000000"})
    assert r.status_code == 401
    assert r.json()["logged_in"] is False
    assert session.get_token(fresh_session) is None


def test_logout_clears_token(fresh_session):
    session.set_token(fresh_session, "jwt")
    r = client.post("/auth/logout", json={"conversation_id": fresh_session})
    assert r.json() == {"logged_in": False}
    assert session.get_token(fresh_session) is None


def test_account_agent_down_gives_503(monkeypatch, fresh_session):
    import httpx
    def boom(*a, **k):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(main.httpx, "post", boom)
    r = client.post("/auth/login", json={"conversation_id": fresh_session, "msisdn": "0712345678", "password": "pw"})
    assert r.status_code == 503
