"""LLMClient: the only way any agent talks to an LLM.   Owner: M1 (shared infrastructure)

    generate(system, prompt, json_schema=None, temperature=0.2) -> str | dict

- Provider order from .env: LLM_PROVIDER (gemini | openai | groq | mock) first, then
  LLM_FALLBACK (default openai) when the first errors or is rate-limited, then any
  other provider that has a key. Our plan: Gemini primary, GPT backup.
- PII masking is applied here to every outgoing prompt, so no agent can forget.
- json_schema given -> the model is asked for JSON; the reply is parsed, and if
  it is not valid JSON we ask the same provider once to repair it.
- 30 s timeout, 2 retries with backoff per provider, latency logged (no text).
- LLM_PROVIDER=mock never touches the network: tests and offline demos.

Live smoke test once keys are in .env:
    python -c "from shared import llm; print(llm.generate('You are terse.', 'Say hi'))"
"""
import json
import logging
import os
import re
import time
from typing import Any, Callable, Optional

from shared.config import settings

log = logging.getLogger("telecare.llm")

TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 2          # per provider, on top of the first attempt
BACKOFF_SECONDS = 0.6

# Tests read the masked prompts from here to prove no PII leaves the process.
LAST_PROMPTS: list[str] = []
_MAX_KEPT = 50


class LLMError(RuntimeError):
    """Raised when every configured provider failed. Callers fall back (e.g. keyword NLU)."""


# ------------------------------------------------------------------ masking

def mask_pii(text: str) -> str:
    """Replace Sri Lankan phone numbers, NICs and emails with placeholders."""
    text = re.sub(r"(?:\+94|0)7\d{8}", "[PHONE]", text)
    text = re.sub(r"\b\d{9}[VvXx]\b|\b\d{12}\b", "[NIC]", text)
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[EMAIL]", text)
    return text


# ------------------------------------------------------------------ providers
# Each provider: (system, prompt, json_mode, temperature) -> text. SDKs are imported
# lazily so the mock path works without them installed.

def _gemini(system: str, prompt: str, json_mode: bool, temperature: float) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key,
                          http_options=types.HttpOptions(timeout=int(TIMEOUT_SECONDS * 1000)))
    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        response_mime_type="application/json" if json_mode else None,
    )
    resp = client.models.generate_content(model=settings.gemini_model, contents=prompt, config=config)
    return resp.text or ""


def _openai(system: str, prompt: str, json_mode: bool, temperature: float) -> str:
    """GPT backup. json_object mode requires the word "JSON" in the prompt; generate() adds it."""
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key, timeout=TIMEOUT_SECONDS)
    extra = {"response_format": {"type": "json_object"}} if json_mode else {}
    resp = client.chat.completions.create(
        model=settings.openai_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        temperature=temperature,
        **extra,
    )
    return resp.choices[0].message.content or ""


def _groq(system: str, prompt: str, json_mode: bool, temperature: float) -> str:
    """Optional third provider (open models). Used only if GROQ_API_KEY is set."""
    from groq import Groq

    client = Groq(api_key=settings.groq_api_key, timeout=TIMEOUT_SECONDS)
    extra = {"response_format": {"type": "json_object"}} if json_mode else {}
    resp = client.chat.completions.create(
        model=settings.groq_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        temperature=temperature,
        **extra,
    )
    return resp.choices[0].message.content or ""


PROVIDERS: dict[str, Callable[[str, str, bool, float], str]] = {
    "gemini": _gemini, "openai": _openai, "groq": _groq,
}


def _has_key(name: str) -> bool:
    keys = {"gemini": settings.gemini_api_key, "openai": settings.openai_api_key, "groq": settings.groq_api_key}
    return bool(keys.get(name))


def provider_chain(primary: str, fallback: Optional[str] = None) -> list[str]:
    """Primary, then the configured fallback (default openai), then anything else with a key."""
    fallback = (fallback or settings.llm_fallback).lower()
    order = [primary, fallback] + [p for p in PROVIDERS if p not in (primary, fallback)]
    seen: list[str] = []
    for p in order:
        if p in PROVIDERS and p not in seen and _has_key(p):
            seen.append(p)
    return seen


# ------------------------------------------------------------------ mock

def _mock(json_schema: Optional[dict]) -> Any:
    """Canned reply. With a schema: every required key set to None, overridden by
    the schema's optional "mock" dict, so callers can validate their handling."""
    if json_schema:
        return {k: None for k in json_schema.get("required", [])} | dict(json_schema.get("mock", {}))
    return "MOCK_REPLY"


# ------------------------------------------------------------------ json helpers

def parse_json(text: str) -> Any:
    """Accept raw JSON, JSON inside ``` fences, or JSON with prose around it."""
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.IGNORECASE)
    try:
        return json.loads(s)
    except ValueError:
        pass
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end > start:
        return json.loads(s[start:end + 1])
    raise ValueError("no JSON object found in model reply")


def _schema_for_prompt(schema: dict) -> str:
    public = {k: v for k, v in schema.items() if k != "mock"}
    return json.dumps(public, ensure_ascii=False)


# ------------------------------------------------------------------ public

def generate(system: str, prompt: str, json_schema: Optional[dict] = None, temperature: float = 0.2) -> Any:
    """Send a PII-masked prompt to the configured provider chain.
    Returns text, or a dict when json_schema is given. Raises LLMError if all fail."""
    provider = os.getenv("LLM_PROVIDER", settings.llm_provider).lower()
    safe_system, safe_prompt = mask_pii(system), mask_pii(prompt)
    json_mode = json_schema is not None
    if json_mode:
        safe_system += "\nReturn only a JSON object matching this schema, no prose: " + _schema_for_prompt(json_schema)

    LAST_PROMPTS.append(safe_system + "\n" + safe_prompt)
    del LAST_PROMPTS[:-_MAX_KEPT]

    if provider == "mock":
        return _mock(json_schema)

    errors: list[str] = []
    for name in provider_chain(provider):
        for attempt in range(MAX_RETRIES + 1):
            started = time.perf_counter()
            try:
                text = PROVIDERS[name](safe_system, safe_prompt, json_mode, temperature)
                log.info("llm provider=%s attempt=%d latency_ms=%d chars=%d",
                         name, attempt, int((time.perf_counter() - started) * 1000), len(text))
                if not json_mode:
                    return text
                try:
                    return parse_json(text)
                except ValueError:
                    # repair-then-retry, once, same provider
                    repaired = PROVIDERS[name](safe_system, "Convert the following into one valid JSON object and "
                                               "return only the JSON:\n" + text, True, 0.0)
                    return parse_json(repaired)
            except Exception as exc:  # network, quota (429), SDK, or still-bad JSON
                errors.append(f"{name}#{attempt}: {type(exc).__name__}: {exc}")
                log.warning("llm provider=%s attempt=%d failed: %s", name, attempt, type(exc).__name__)
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_SECONDS * (attempt + 1))
    if not errors:
        raise LLMError(f"no provider configured: LLM_PROVIDER={provider!r} and no API key found in .env")
    raise LLMError("all providers failed: " + " | ".join(errors))
