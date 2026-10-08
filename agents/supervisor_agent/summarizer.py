"""Conversation -> structured ticket summary.   Owner: M4

    summarize(history: list[dict]) -> {issue, key_entities, what_was_tried, customer_mood, priority}

Mask PII first, then one shared.llm.generate call with a JSON schema.
If the LLM is unavailable (no key, timeout, rate limit, mock mode),
fall back to a deterministic summary so the ticket is still created.
"""
from shared.security import mask_pii
from shared.llm import generate, LLMError


FALLBACK_SUMMARY = {
    "issue": "Customer requires human assistance (auto-summary unavailable).",
    "key_entities": [],
    "what_was_tried": "Automated triage",
    "customer_mood": "frustrated",
    "priority": "normal",
}


def summarize(history: list[dict]) -> dict:
    # 1. Mask PII before anything leaves this process
    masked = []
    for turn in history:
        masked.append({
            "role": turn.get("role", "user"),
            "text": mask_pii(turn.get("text", "")),
        })

    # 2. Build the prompt
    history_text = "\n".join(f"{t['role']}: {t['text']}" for t in masked)

    system_prompt = (
        "You are a telecom care supervisor. Summarize the conversation "
        "into a structured ticket."
    )
    user_prompt = (
        f"Conversation:\n{history_text}\n\n"
        "Return a JSON object with keys: issue, key_entities, what_was_tried, "
        "customer_mood, priority."
    )

    schema = {
        "type": "object",
        "properties": {
            "issue": {"type": "string"},
            "key_entities": {"type": "array", "items": {"type": "string"}},
            "what_was_tried": {"type": "string"},
            "customer_mood": {"type": "string"},
            "priority": {"type": "string"},
        },
        "required": ["issue", "customer_mood", "priority"],
    }

    # 3. Call the LLM — never let a failure crash the escalation
    try:
        result = generate(system_prompt, user_prompt, json_schema=schema)
    except LLMError:
        result = None

    # 4. Fallback if the LLM failed or returned empty
    if not result or not result.get("issue"):
        return dict(FALLBACK_SUMMARY)

    return result