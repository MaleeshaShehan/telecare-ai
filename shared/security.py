"""Security helpers used by the Orchestrator and shared by all agents.   Owner: M1

    sanitize(text) -> str         strip HTML / control chars, cap at 1000 chars
    is_injection(text) -> bool    prompt-injection phrase list (grow it as attacks are found)
    mask_pii(text) -> str         phones / NICs / emails -> [PHONE] [NIC] [EMAIL]

JWT issue/verify and Fernet encryption live in the Account Agent (agents/account_agent/auth.py,
repository.py): nobody else needs them, so they are not shared.
"""
import html
import re

from shared.llm import mask_pii  # single implementation, re-exported  # noqa: F401

MAX_INPUT_CHARS = 1000

# Known injection phrases. Lower-case substring match. Extend as attacks are found;
# the security test log claims at least 10 are blocked.
INJECTION_PATTERNS: tuple[str, ...] = (
    "ignore previous instructions",
    "ignore all instructions",
    "ignore the above",
    "system prompt",
    "reveal all",
    "act as",
    "you are now",
    "disregard your rules",
    "developer mode",
    "jailbreak",
    "print your instructions",
)


def sanitize(text: str) -> str:
    """Remove HTML tags and control characters, unescape entities, cap length."""
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")
    return text.strip()[:MAX_INPUT_CHARS]


def is_injection(text: str) -> bool:
    """True when the message looks like a prompt-injection attempt."""
    lowered = text.lower()
    return any(p in lowered for p in INJECTION_PATTERNS)
