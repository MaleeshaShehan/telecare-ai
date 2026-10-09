"""Security helpers used by the Orchestrator and shared by all agents.   Owner: M1

    sanitize(text) -> str                 strip HTML / control chars, cap at 1000 chars
    is_injection(text) -> bool            prompt-injection verdict (score >= BLOCK_THRESHOLD)
    injection_findings(text) -> Finding   score + the rule names that fired (for the audit log)
    mask_pii(text) -> str                 phones / NICs / emails -> [PHONE] [NIC] [EMAIL]
    contains_prompt_leak(text) -> bool    does an outgoing reply contain a system-prompt fragment

Version 2 (hardened after the Assignment 2 prompt-injection audit). Version 1 was a
substring match on eleven phrases: it missed paraphrases, leetspeak and encoded
payloads, and refused 18 % of benign telecom questions. Version 2:

  1. normalises the text before matching: Unicode NFKC, zero-width characters
     removed, lower-cased, common leetspeak mapped back, punctuation collapsed;
  2. matches weighted regular expressions that need an attack *structure*
     (verb + object), so "ignore the previous bill" and "act as my guide" pass
     while "ignore previous instructions" and "act as the database" do not;
  3. decodes base64 blobs and scores the decoded text as well;
  4. blocks when the total score reaches BLOCK_THRESHOLD and reports which
     rules fired, so the audit log explains every refusal without storing text.

JWT issue/verify and Fernet encryption live in the Account Agent.
"""
from __future__ import annotations

import base64
import html
import re
import unicodedata
from dataclasses import dataclass, field

from shared.llm import mask_pii  # single implementation, re-exported  # noqa: F401

MAX_INPUT_CHARS = 1000
BLOCK_THRESHOLD = 1.0

# ------------------------------------------------------------------ normalisation

_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "|": "l", "!": "i"})
_ZERO_WIDTH = re.compile(r"[​‌‍⁠﻿­]")
_NON_ALNUM = re.compile(r"[^a-z0-9\s]")
_SPACES = re.compile(r"\s+")


def normalise(text: str, leet: bool = False) -> str:
    """Canonical lower-case form used only for matching, never for routing."""
    t = unicodedata.normalize("NFKC", text or "")
    t = _ZERO_WIDTH.sub("", t).lower()
    if leet:
        t = t.translate(_LEET)
    t = _NON_ALNUM.sub(" ", t)
    return _SPACES.sub(" ", t).strip()


# ------------------------------------------------------------------ rules
# (name, compiled regex over the normalised text, weight). A single 1.0 rule blocks;
# two medium rules together block. Keep the object nouns tight to avoid false positives.

_INSTR = r"(instructions?|rules?|guidelines?|prompts?|directives?|programming|training|constraints?|system message)"
_ROLE = (r"(database|db|admin(istrator)?|sysadmin|system|developer|engineer|root|superuser|operator console|"
         r"unrestricted|unfiltered|uncensored|evil|hacker|jailbroken|billing (system|database|backend)|backend|server|api|"
         r"(ai|model|assistant|bot) (with|without) (no |any )?(rules|restrictions|limits|filters))")

INJECTION_RULES: tuple[tuple[str, re.Pattern[str], float], ...] = (
    ("override_instructions",
     re.compile(r"\b(ignore|disregard|discard|skip|bypass|override|forget|drop)\b(?: \w+){0,4} " + _INSTR + r"\b"), 1.0),
    ("forget_context",
     re.compile(r"\b(forget|erase|clear|wipe|reset)\b(?: \w+){0,3} (everything|all|anything|what)\b(?: \w+){0,6} (told|said|instructed|taught|learned|before|earlier|previous|previously|above)\b"), 1.0),
    ("from_now_on_directive",
     re.compile(r"\b(from now on|starting now|for the rest of this (chat|conversation|session)|in this (chat|conversation) you)\b"), 0.7),
    ("output_format_hijack",
     re.compile(r"\b(answer|respond|reply)\b(?: \w+){0,4} only\b(?: \w+){0,3} (with|using|in)\b(?: \w+){0,3} (words?|phrase|text|sentence|string)\b"), 0.6),
    ("system_prompt_mention",   # alone it is only a hint ("my phone shows a system message"); with a verb it blocks
     re.compile(r"\b(system|hidden|secret|initial|internal|original|developer|master) (prompt|instructions?|message)\b"), 0.7),
    ("ask_for_instructions",
     re.compile(r"\b(what|which)\b(?: \w+){0,5} " + _INSTR + r"\b(?: \w+){0,6} (given|told|have|had|received|loaded|configured)\b"), 1.0),
    ("reveal_own_prompt",       # "your instructions", "its prompt": the assistant's own configuration
     re.compile(r"\b(reveal|show|print|repeat|dump|output|display|recite|leak|expose|what is|what s|whats|tell me)\b(?: \w+){0,3} (your|its)(?: \w+){0,2} " + _INSTR + r"\b"), 1.0),
    ("reveal_rules_generic",    # "show me the rules for the student package" is a normal question
     re.compile(r"\b(reveal|show|print|repeat|dump|output|display)\b(?: \w+){0,3} (the|all) " + _INSTR + r"\b"), 0.4),
    ("role_override",
     re.compile(r"\b(you are now|you re now|act as|acting as|pretend (to be|you are|you re)|role ?play as|behave as|behave like|imagine you are|simulate (being|a)|become)\b(?: \w+){0,3} (an? |the |my )?" + _ROLE + r"\b"), 1.0),
    ("jailbreak_mode",
     re.compile(r"\b(enable|enter|activate|switch to|turn on|unlock|engage)\b(?: \w+){0,2} (developer|dan|god|unrestricted|debug|admin|sudo) mode\b|\bdo anything now\b|\bjailbreak (mode|prompt|yourself|the (ai|assistant|model|bot))\b"), 1.0),
    ("mass_exfiltration",
     re.compile(r"\b(reveal|show|list|print|dump|export|display|give me|send me)\b(?: \w+){0,3} (all|every|each|entire)\b(?: \w+){0,3} (bills?|customers?|subscribers?|users?|accounts?|records?|rows?|tables?|data|numbers?|passwords?|secrets?|keys?|tokens?)\b"), 0.8),
    ("code_or_sql",
     re.compile(r"\b(drop table|delete from|union select|select \* from|insert into|or 1 1|exec |os system|subprocess|import os)\b"), 1.0),
    ("encoded_payload",
     re.compile(r"\b(decode|base64|rot13|hex)\b(?: \w+){0,6} (follow|execute|run|obey|do)\b"), 0.5),
)

# Rule names, kept for callers that only want the list (and for the security test log).
INJECTION_PATTERNS: tuple[str, ...] = tuple(name for name, _, _ in INJECTION_RULES)

_B64_BLOB = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")


@dataclass
class Finding:
    score: float = 0.0
    rules: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.score >= BLOCK_THRESHOLD


def _score(norm: str) -> Finding:
    f = Finding()
    for name, rx, weight in INJECTION_RULES:
        if rx.search(norm):
            f.score += weight
            f.rules.append(name)
    return f


def _decoded_blobs(text: str) -> list[str]:
    out = []
    for blob in _B64_BLOB.findall(text or ""):
        try:
            raw = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=False)
            s = raw.decode("utf-8")
        except Exception:
            continue
        if s.isprintable() and len(s) >= 12:
            out.append(s)
    return out


def injection_findings(text: str) -> Finding:
    """Score the message on its plain, leet-folded and base64-decoded forms; keep the highest."""
    candidates = [normalise(text), normalise(text, leet=True)]
    for decoded in _decoded_blobs(text):
        candidates.append(normalise(decoded))
        candidates.append(normalise(decoded, leet=True))
    best = Finding()
    seen = set()
    for i, c in enumerate(candidates):
        f = _score(c)
        if i >= 2 and f.rules:                      # came from a decoded blob
            f.rules = [f"decoded:{r}" for r in f.rules]
            f.score = max(f.score, BLOCK_THRESHOLD)  # an encoded attack is always blocked
        if f.score > best.score:
            best = f
        seen.update(f.rules)
    best.rules = sorted(set(best.rules))
    return best


def is_injection(text: str) -> bool:
    """True when the message looks like a prompt-injection or jailbreak attempt."""
    return injection_findings(text).blocked


# ------------------------------------------------------------------ sanitisation

def sanitize(text: str) -> str:
    """Remove HTML tags and control characters, unescape entities, cap length."""
    text = re.sub(r"<[^>]+>", "", text or "")
    text = html.unescape(text)
    text = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")
    return text.strip()[:MAX_INPUT_CHARS]


# ------------------------------------------------------------------ output guard

_PROMPT_FRAGMENTS: list[str] = []


def register_system_prompt(prompt: str) -> None:
    """Agents (or the composer) register their system prompts so replies can be
    checked for leakage. Fragments of 40+ characters are kept, never logged."""
    for chunk in re.split(r"(?<=[.!?])\s+", (prompt or "").strip()):
        chunk = chunk.strip()
        if len(chunk) >= 40:
            _PROMPT_FRAGMENTS.append(chunk.lower())


def contains_prompt_leak(text: str) -> bool:
    """True when an outgoing reply quotes a registered system prompt."""
    low = (text or "").lower()
    return any(frag in low for frag in _PROMPT_FRAGMENTS)
