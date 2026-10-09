"""NLU: LLM path, validation, retry and fallback."""
from agents.orchestrator import nlu
from shared import llm
from shared.intents import Intent
from datetime import date


def test_mock_provider_falls_back_to_keywords():
    # The mock returns nulls, which fail validation, so the keyword path answers.
    out = nlu.classify("roaming rates for India")
    assert out["method"] == "keywords"
    assert out["intent"] == Intent.ROAMING_ADVICE


def test_month_specific_bill_is_classified_and_normalized():
    out = nlu.classify_keywords("Show me my bill for September 2026")
    assert out["intent"] == Intent.BILL_BY_MONTH
    assert out["entities"]["billing_period"] == "2026-09"
    assert nlu.extract_billing_period("invoice for 2026/08") == "2026-08"
    assert nlu.extract_billing_period("May I see my bill?", date(2026, 10, 9)) is None


def test_valid_llm_json_is_used(monkeypatch):
    monkeypatch.setattr(llm, "generate", lambda *a, **k: {
        "intent": "plan_advice", "confidence": 0.93,
        "entities": {"package_name": None, "country": None, "data_amount": "20GB"},
        "needs_clarification": False})
    out = nlu.classify("I stream a lot, what suits me?")
    assert out["method"] == "llm"
    assert out["intent"] == Intent.PLAN_ADVICE
    assert out["confidence"] == 0.93
    assert out["entities"]["data_amount"] == "20GB"


def test_llm_json_as_string_is_parsed(monkeypatch):
    monkeypatch.setattr(llm, "generate", lambda *a, **k:
                        '{"intent": "quota_check", "confidence": 0.8, "entities": {}, "needs_clarification": false}')
    assert nlu.classify("how much data left")["intent"] == Intent.QUOTA_CHECK


def test_regex_entities_merge_with_llm_entities(monkeypatch):
    monkeypatch.setattr(llm, "generate", lambda *a, **k: {
        "intent": "bill_enquiry", "confidence": 0.9, "entities": {"country": None}, "needs_clarification": False})
    out = nlu.classify("I paid Rs. 1,000 for 0712345678")
    assert out["entities"]["phone"] == ["0712345678"]
    assert out["entities"]["amount"] == ["Rs. 1,000"]


def test_bad_json_retries_once_then_falls_back(monkeypatch):
    calls = []
    def bad(*a, **k):
        calls.append(1)
        return {"intent": "not_real", "confidence": 5}
    monkeypatch.setattr(llm, "generate", bad)
    out = nlu.classify("roaming in Dubai")
    assert len(calls) == 2
    assert out["method"] == "keywords"
    assert out["intent"] == Intent.ROAMING_ADVICE


def test_provider_exception_falls_back_without_crashing(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("quota exceeded")
    monkeypatch.setattr(llm, "generate", boom)
    out = nlu.classify("why is my bill higher")
    assert out["method"] == "keywords"
    assert out["intent"] == Intent.BILL_ENQUIRY


def test_prompt_sent_to_llm_is_pii_masked():
    llm.LAST_PROMPTS.clear()
    nlu.classify("my number is 0712345678 and mail is me@x.lk")
    assert llm.LAST_PROMPTS
    assert "0712345678" not in llm.LAST_PROMPTS[-1]
    assert "me@x.lk" not in llm.LAST_PROMPTS[-1]
