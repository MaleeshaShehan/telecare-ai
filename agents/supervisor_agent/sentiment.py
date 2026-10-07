"""Sentiment + escalation rules.   Owner: M4

    assess(message, intent, failed_count) -> {sentiment, score, escalate, reason, priority}

Rules (BUILD_PLAN section 8):
    VADER compound <= -0.5                        -> escalate, high
    -0.5 < compound <= -0.2                       -> one LLM call to confirm; escalate if frustrated
    keywords human / agent / manager / call me    -> escalate, normal
    intent == complaint                           -> escalate
    failed_count >= 2                             -> escalate, normal
"""
