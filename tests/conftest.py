"""Shared pytest setup. Tests never call a real LLM and never touch the real audit DB."""
import os
from pathlib import Path

import pytest

os.environ["LLM_PROVIDER"] = "mock"
os.environ.setdefault("INTERNAL_API_KEY", "test-internal-key")
os.environ["ACCOUNT_DB_BACKEND"] = "sqlite"


@pytest.fixture(autouse=True)
def isolated_audit_db(tmp_path, monkeypatch):
    """Point shared.audit at a temp file so tests leave no rows behind."""
    import shared.audit as audit
    monkeypatch.setattr(audit, "AUDIT_DB", tmp_path / "audit.db")
    yield


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Each test starts with a clean rate-limit window."""
    from agents.orchestrator.main import limiter
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def fresh_session():
    """Give a test its own conversation id with no state behind it."""
    import uuid
    from agents.orchestrator import session
    cid = f"t-{uuid.uuid4()}"
    yield cid
    session.reset(cid)
