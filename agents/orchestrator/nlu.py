"""Intent classification + NER in one LLM call, with safe fallbacks.   Owner: M1

Order of work for every message:
1. Regex entities (phone, amount) and optional spaCy entities (DATE, GPE).
2. One LLM call via shared.llm.generate asking for strict JSON.
3. Validate with Pydantic. Invalid JSON -> retry once -> fall back to the
   keyword classifier. The system never crashes on a bad LLM reply.

Returned dict: {intent, confidence, entities, needs_clarification, method}
where method is "llm" or "keywords" (shown in the agent trace).
"""
import json
import re

from pydantic import BaseModel, Field, ValidationError

from shared import llm
from shared.intents import Intent

PHONE_RE = re.compile(r"(?:\+94|0)7\d{8}")
AMOUNT_RE = re.compile(r"Rs\.?\s?[\d,]+")

# ---------------------------------------------------------------- LLM path

class NLUResult(BaseModel):
    """Shape the LLM must return. Pydantic rejects anything else."""
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    entities: dict = Field(default_factory=dict)
    needs_clarification: bool = False


NLU_SCHEMA = {
    "type": "object",
    "required": ["intent", "confidence", "entities", "needs_clarification"],
    "properties": {
        "intent": {"type": "string", "enum": [i.value for i in Intent]},
        "confidence": {"type": "number"},
        "entities": {
            "type": "object",
            "properties": {
                "package_name": {"type": ["string", "null"]},
                "country": {"type": ["string", "null"]},
                "data_amount": {"type": ["string", "null"]},
            },
        },
        "needs_clarification": {"type": "boolean"},
    },
}

NLU_SYSTEM = (
    "You are the intent classifier for a telecom customer-care assistant. "
    "Classify the customer's message into exactly one intent from this list: "
    + ", ".join(i.value for i in Intent)
    + ". Extract entities package_name, country and data_amount (null if absent). "
    "Set needs_clarification true only if the message is too vague to route. "
    "Return strict JSON with keys intent, confidence (0-1), entities, needs_clarification. "
    "No prose."
)


def classify_llm(message: str) -> NLUResult | None:
    """Ask the LLM. Return None if, after one retry, we still have no valid result."""
    for _attempt in range(2):
        try:
            raw = llm.generate(NLU_SYSTEM, message, json_schema=NLU_SCHEMA)
            if isinstance(raw, str):
                raw = json.loads(raw)
            return NLUResult.model_validate(raw)
        except (ValidationError, ValueError, TypeError):
            continue  # bad JSON or wrong shape: retry once
        except Exception:  # provider missing, network, quota: do not crash the turn
            return None
    return None

# ------------------------------------------------------------ entities

_nlp = None


def _spacy():
    """Load spaCy once if it is installed; otherwise return None."""
    global _nlp
    if _nlp is None:
        try:
            import spacy
            _nlp = spacy.load("en_core_web_sm")
        except Exception:
            _nlp = False
    return _nlp or None


def extract_entities(message: str) -> dict:
    ents = {
        "phone": PHONE_RE.findall(message),
        "amount": AMOUNT_RE.findall(message),
        "date": [],
        "country": None,
        "package_name": None,
        "data_amount": None,
    }
    nlp = _spacy()
    if nlp:
        doc = nlp(message)
        ents["date"] = [e.text for e in doc.ents if e.label_ == "DATE"]
        gpes = [e.text for e in doc.ents if e.label_ == "GPE"]
        ents["country"] = gpes[0] if gpes else None
    return ents

# ---------------------------------------------------- keyword fallback

# Order matters: more specific intents first.
KEYWORDS: list[tuple[Intent, tuple[str, ...]]] = [
    (Intent.COMPLAINT, ("complaint", "ridiculous", "useless", "worst", "manager", "human", "agent")),
    (Intent.BILL_ENQUIRY, ("bill", "charged", "charge", "payment", "invoice", "higher this month")),
    (Intent.QUOTA_CHECK, ("quota", "balance", "data left", "remaining", "how much data")),
    (Intent.ROAMING_ADVICE, ("roaming", "abroad", "overseas", "india", "dubai", "travel")),
    (Intent.COVERAGE_OR_OUTAGE_INFO, ("coverage", "outage", "signal", "no network", "down in")),
    (Intent.TROUBLESHOOTING, ("not working", "slow", "cannot connect", "can't connect", "apn", "reset")),
    (Intent.PLAN_ADVICE, ("which plan", "what plan", "suits me", "recommend", "best plan", "suggest")),
    (Intent.TARIFF_QUERY, ("price", "cost", "how much", "rate", "tariff", "rs")),
    (Intent.PACKAGE_INFO, ("package", "plan", "gb", "anytime", "unlimited", "bundle")),
]


def classify_keywords(message: str) -> dict:
    lowered = message.lower()
    for intent, words in KEYWORDS:
        if any(w in lowered for w in words):
            return {"intent": intent, "confidence": 0.6, "entities": extract_entities(message),
                    "needs_clarification": False, "method": "keywords"}
    return {"intent": Intent.OUT_OF_SCOPE, "confidence": 0.5, "entities": extract_entities(message),
            "needs_clarification": False, "method": "keywords"}

# ------------------------------------------------------------- public

def classify(message: str) -> dict:
    """LLM first; keyword classifier if the LLM is unavailable or returns junk.
    Regex/spaCy entities are always merged in so phone numbers never depend on the LLM."""
    result = classify_llm(message)
    if result is None:
        return classify_keywords(message)
    entities = extract_entities(message)
    for key, value in result.entities.items():
        if value is not None:
            entities[key] = value
    return {"intent": result.intent, "confidence": result.confidence, "entities": entities,
            "needs_clarification": result.needs_clarification, "method": "llm"}
