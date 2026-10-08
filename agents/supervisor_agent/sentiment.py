"""Sentiment + escalation rules.   Owner: M4

    assess(message, intent, failed_count) -> {sentiment, score, escalate, reason, priority}

Rules (BUILD_PLAN section 8):
    VADER compound <= -0.5                        -> escalate, high
    -0.5 < compound <= -0.2                       -> one LLM call to confirm; escalate if frustrated
    keywords human / agent / manager / call me    -> escalate, normal
    intent == complaint                           -> escalate
    failed_count >= 2                             -> escalate, normal
"""
"""Sentiment + escalation rules.   Owner: M4

    assess(message, intent, failed_count) -> {sentiment, score, escalate, reason, priority}
"""

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

analyzer = SentimentIntensityAnalyzer()

def assess(message: str, intent: str, failed_count: int) -> dict:
    # 1. VADER Sentiment
    scores = analyzer.polarity_scores(message)
    compound = scores["compound"]

    # 2. Rules Engine
    escalate = False
    reason = "none"
    priority = "normal"

    # Rule A: Strong negative sentiment
    if compound <= -0.5:
        escalate = True
        reason = "vader<=-0.5"
        priority = "high"

    # Rule B: Asked for a human
    keywords = ["human", "agent", "manager", "call me", "speak to someone"]
    if any(k in message.lower() for k in keywords):
        escalate = True
        reason = "asked_for_human"
        priority = "normal"

    # Rule C: System keeps failing
    if failed_count >= 2:
        escalate = True
        reason = "repeated_failures"
        priority = "normal"

    # Rule D: Complaint intent
    if intent == "complaint":
        escalate = True
        reason = "complaint_intent"

    return {
        "sentiment": "negative" if compound < -0.05 else ("positive" if compound > 0.05 else "neutral"),
        "score": compound,
        "escalate": escalate,
        "reason": reason,
        "priority": priority
    }