"""shared/llm.py: masking, provider chain, fallback, JSON handling. No network."""
import pytest

from shared import llm


@pytest.fixture
def real_mode(monkeypatch):
    """Pretend Gemini and OpenAI keys exist with Gemini primary, but swap the SDK calls for fakes."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setattr(llm.settings, "llm_fallback", "openai")
    monkeypatch.setattr(llm.settings, "gemini_api_key", "k1")
    monkeypatch.setattr(llm.settings, "openai_api_key", "k2")
    monkeypatch.setattr(llm.settings, "groq_api_key", "")
    monkeypatch.setattr(llm, "BACKOFF_SECONDS", 0)
    calls = []

    def make(name, behaviour):
        def fake(system, prompt, json_mode, temperature):
            calls.append((name, prompt))
            out = behaviour(prompt)
            if isinstance(out, Exception):
                raise out
            return out
        return fake

    def install(gemini=lambda p: "gemini says hi", openai=lambda p: "gpt says hi"):
        monkeypatch.setattr(llm, "PROVIDERS", {"gemini": make("gemini", gemini), "openai": make("openai", openai),
                                               "groq": make("groq", lambda p: "groq says hi")})
        return calls
    return install


def test_mock_mode_never_calls_a_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setattr(llm, "PROVIDERS", {})
    assert llm.generate("s", "p") == "MOCK_REPLY"
    assert llm.generate("s", "p", json_schema={"required": ["a", "b"], "mock": {"b": 1}}) == {"a": None, "b": 1}


def test_prompt_is_masked_before_leaving(real_mode):
    calls = real_mode()
    llm.generate("sys", "call 0712345678, NIC 912345678V, mail a@b.lk")
    _, prompt = calls[0]
    assert "0712345678" not in prompt and "912345678V" not in prompt and "a@b.lk" not in prompt
    assert "[PHONE]" in prompt and "[NIC]" in prompt and "[EMAIL]" in prompt


def test_primary_provider_used_first(real_mode):
    calls = real_mode()
    assert llm.generate("s", "p") == "gemini says hi"
    assert [c[0] for c in calls] == ["gemini"]


def test_falls_back_to_gpt_after_gemini_retries(real_mode):
    calls = real_mode(gemini=lambda p: RuntimeError("429 quota"))
    assert llm.generate("s", "p") == "gpt says hi"
    assert [c[0] for c in calls] == ["gemini"] * (llm.MAX_RETRIES + 1) + ["openai"]


def test_groq_is_skipped_without_a_key(real_mode):
    calls = real_mode(gemini=lambda p: RuntimeError("down"), openai=lambda p: RuntimeError("down too"))
    with pytest.raises(llm.LLMError):
        llm.generate("s", "p")
    assert "groq" not in [c[0] for c in calls]


def test_no_keys_raises_clear_error(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    for k in ("gemini_api_key", "openai_api_key", "groq_api_key"):
        monkeypatch.setattr(llm.settings, k, "")
    with pytest.raises(llm.LLMError, match="no provider configured"):
        llm.generate("s", "p")


def test_json_in_fences_is_parsed(real_mode):
    real_mode(gemini=lambda p: '```json\n{"intent": "quota_check", "confidence": 0.9}\n```')
    out = llm.generate("s", "p", json_schema={"required": ["intent"]})
    assert out == {"intent": "quota_check", "confidence": 0.9}


def test_bad_json_is_repaired_once(real_mode):
    calls = real_mode(gemini=lambda p: '{"fixed": true}' if "Convert the following" in p else "Sure! intent is quota")
    assert llm.generate("s", "p", json_schema={"required": ["fixed"]}) == {"fixed": True}
    assert len(calls) == 2


def test_schema_is_appended_to_system_prompt_without_mock_key(real_mode):
    real_mode(gemini=lambda p: '{"x": 1}')
    llm.LAST_PROMPTS.clear()
    llm.generate("s", "p", json_schema={"required": ["x"], "mock": {"x": 1}})
    assert '"required": ["x"]' in llm.LAST_PROMPTS[-1]
    assert "mock" not in llm.LAST_PROMPTS[-1]


def test_provider_chain_order_and_filtering(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_fallback", "openai")
    monkeypatch.setattr(llm.settings, "gemini_api_key", "k")
    monkeypatch.setattr(llm.settings, "openai_api_key", "k")
    monkeypatch.setattr(llm.settings, "groq_api_key", "")
    assert llm.provider_chain("gemini") == ["gemini", "openai"]
    assert llm.provider_chain("openai") == ["openai", "gemini"]
    monkeypatch.setattr(llm.settings, "gemini_api_key", "")
    assert llm.provider_chain("gemini") == ["openai"]
    monkeypatch.setattr(llm.settings, "groq_api_key", "k")
    assert llm.provider_chain("gemini") == ["openai", "groq"]


def test_fallback_setting_is_respected(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_fallback", "groq")
    for k in ("gemini_api_key", "openai_api_key", "groq_api_key"):
        monkeypatch.setattr(llm.settings, k, "k")
    assert llm.provider_chain("gemini") == ["gemini", "groq", "openai"]
