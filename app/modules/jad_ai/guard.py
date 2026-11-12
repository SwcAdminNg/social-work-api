"""Input and output checks for JAD AI.

Defence in depth against prompt injection:
1. Learner text is cleaned (Unicode-normalised, invisible and control characters
   removed, length capped) before anything else sees it.
2. Obvious override attempts ("ignore your instructions", "show me your system
   prompt", fake role tags...) are scored here and turned away without calling the
   model at all, which also saves tokens.
3. Lesson material is fenced in tags with a random per-request name and any copy of
   the fence inside it is removed, so a document can't close the fence and talk to
   the model as if it were us (see prompt.py).
4. The system prompt carries a random canary; an answer that contains it, or the
   fence name, is withheld (see `leaks_prompt`).
"""

import re
import unicodedata

# Zero-width and bidirectional control characters, used to hide instructions.
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿­]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# (pattern, weight). A message scoring >= BLOCK_SCORE is turned away.
BLOCK_SCORE = 3
_INJECTION_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"\b(ignore|disregard|forget|override|bypass|skip)\b.{0,40}\b(previous|prior|above|earlier|all|any|your|the|these|those)\b.{0,30}\b(instruction|instructions|rules|prompt|prompts|guidelines|directions|context|policy|policies)\b", re.I), 3),
    (re.compile(r"\b(system|developer|hidden|initial|original|secret)\s+(prompt|message|instructions?)\b", re.I), 3),
    (re.compile(r"\b(reveal|show|print|repeat|output|display|tell me|leak|dump|copy)\b.{0,40}\b(your|the)\b.{0,20}\b(instructions?|prompt|rules|configuration|guidelines)\b", re.I), 3),
    (re.compile(r"\b(developer|god|admin|sudo|jailbreak|dan|unrestricted|unfiltered)\s+mode\b", re.I), 3),
    (re.compile(r"\bdo anything now\b|\bjailbreak\b", re.I), 3),
    (re.compile(r"\byou are (now|no longer)\b|\bfrom now on,? you (are|will|must)\b|\bnew (instructions|rules|persona)\b", re.I), 2),
    (re.compile(r"<\|?(im_start|im_end|system|endoftext)\|?>|\[/?(INST|SYS)\]|<</?SYS>>", re.I), 3),
    (re.compile(r"^\s*(#+\s*)?(system|assistant|developer)\s*:", re.I | re.M), 2),
    (re.compile(r"</?\s*material[-\w]*\s*>|</?\s*quiz-question[-\w]*\s*>", re.I), 3),
    (re.compile(r"\b(pretend|act as if|roleplay as)\b.{0,30}\b(no|without)\b.{0,15}\b(rules|restrictions|limits|filters)\b", re.I), 3),
    (re.compile(r"\bprompt injection\b|\bcanary\b", re.I), 1),
    # Long base64/hex blobs are a common way to smuggle instructions.
    (re.compile(r"[A-Za-z0-9+/]{120,}={0,2}"), 2),
]

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?:\+?\d[\d\s-]{8,}\d)")


def clean_input(text: str, max_chars: int) -> str:
    """Normalise learner text: NFKC (folds look-alike letters), no invisible or
    control characters, tidy whitespace, capped length."""
    text = unicodedata.normalize("NFKC", text or "")
    text = _INVISIBLE.sub("", text)
    text = _CONTROL.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:max_chars]


def injection_score(text: str) -> int:
    return sum(weight for pattern, weight in _INJECTION_PATTERNS if pattern.search(text))


def is_injection(text: str) -> bool:
    return injection_score(text) >= BLOCK_SCORE


def has_personal_data(text: str) -> bool:
    """Questions with an email address or phone number are never shared via the cache."""
    return bool(_EMAIL.search(text) or _PHONE.search(text))


def fence_material(text: str, fence: str) -> str:
    """Remove anything that looks like our fence tags from untrusted material."""
    text = _INVISIBLE.sub("", unicodedata.normalize("NFKC", text or ""))
    return re.sub(r"</?\s*(material|quiz-question)[-\w]*\s*>", "", text, flags=re.I).replace(fence, "")


def leaks_prompt(answer: str, canary: str, fence: str) -> bool:
    return canary in answer or fence in answer


BLOCKED_REPLY = (
    "I can only help with this lesson and your social work studies, and I can't change "
    "how I work or share my setup. What would you like to know about **{title}**?"
)

WITHHELD_REPLY = (
    "Sorry, I can't share that. Let's get back to the lesson: what would you like to "
    "understand better about **{title}**?"
)
