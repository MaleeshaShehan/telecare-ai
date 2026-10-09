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
from datetime import date

from pydantic import BaseModel, Field, ValidationError

from shared import llm
from shared.intents import Intent

PHONE_RE = re.compile(r"(?:\+94|0)7\d{8}")
AMOUNT_RE = re.compile(r"Rs\.?\s?[\d,]+")
YEAR_MONTH_RE = re.compile(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])\b")
MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2,
    "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
MONTH_NAME = "|".join(sorted(MONTHS, key=len, reverse=True))
NAMED_MONTH_RE = re.compile(
    rf"\b(?:for|from|in|of)\s+({MONTH_NAME})(?:\s+(20\d{{2}}))?\b"
    rf"|\b({MONTH_NAME})\s+(20\d{{2}})\b"
    rf"|\b({MONTH_NAME})\s+(?:bill|invoice)\b",
    re.IGNORECASE,
)
BILL_WORDS = ("bill", "invoice", "charged", "charges")

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
                "billing_period": {"type": ["string", "null"]},
            },
        },
        "needs_clarification": {"type": "boolean"},
    },
}

NLU_SYSTEM = (
    "You are the intent classifier for a telecom customer-care assistant. "
    "Classify the customer's message into exactly one intent from this list: "
    + ", ".join(i.value for i in Intent)
    + ". Extract entities package_name, country, data_amount and billing_period. "
    "billing_period must be YYYY-MM when the customer names a billing month, otherwise null. "
    "Use bill_by_month for a bill or invoice request naming a specific month. "
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
        "billing_period": extract_billing_period(message),
    }
    nlp = _spacy()
    if nlp:
        doc = nlp(message)
        ents["date"] = [e.text for e in doc.ents if e.label_ == "DATE"]
        gpes = [e.text for e in doc.ents if e.label_ == "GPE"]
        ents["country"] = gpes[0] if gpes else None
    return ents


def extract_billing_period(message: str, today: date | None = None) -> str | None:
    """Return an explicit billing month as YYYY-MM without depending on spaCy."""
    numeric = YEAR_MONTH_RE.search(message)
    if numeric:
        return f"{int(numeric.group(1)):04d}-{int(numeric.group(2)):02d}"

    named = NAMED_MONTH_RE.search(message)
    if not named:
        return None
    month_name = next(value for value in (named.group(1), named.group(3), named.group(5)) if value)
    year_text = named.group(2) or named.group(4)
    month = MONTHS[month_name.lower()]
    current = today or date.today()
    year = int(year_text) if year_text else current.year
    if not year_text and month > current.month:
        year -= 1
    return f"{year:04d}-{month:02d}"


def _is_month_bill_request(message: str, entities: dict) -> bool:
    lowered = message.lower()
    return bool(entities.get("billing_period")) and any(word in lowered for word in BILL_WORDS)

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
    entities = extract_entities(message)
    if _is_month_bill_request(message, entities):
        return {"intent": Intent.BILL_BY_MONTH, "confidence": 0.8, "entities": entities,
                "needs_clarification": False, "method": "keywords"}
    for intent, words in KEYWORDS:
        if any(w in lowered for w in words):
            return {"intent": intent, "confidence": 0.6, "entities": entities,
                    "needs_clarification": False, "method": "keywords"}
    return {"intent": Intent.OUT_OF_SCOPE, "confidence": 0.5, "entities": entities,
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
    intent = Intent.BILL_BY_MONTH if _is_month_bill_request(message, entities) else result.intent
    return {"intent": intent, "confidence": result.confidence, "entities": entities,
            "needs_clarification": result.needs_clarification, "method": "llm"}
