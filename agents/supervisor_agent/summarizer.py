"""Conversation -> structured ticket summary.   Owner: M4

    summarize(history: list[dict]) -> {issue, key_entities, what_was_tried, customer_mood, priority}

Mask PII first (shared.security.mask_pii), then one shared.llm.generate call
with a JSON schema.
"""
