"""Blocks foul language in user-submitted community chat text.

Add or remove entries in BLOCKED_TERMS to tune the list - each entry is a
single word or a space-separated phrase, lowercase. Matching is done on
whole normalized words (not raw substrings), so legitimate words that merely
*contain* a blocked term as a substring - "classic", "Dickens", "Scunthorpe" -
are never flagged; only an actual occurrence of the term as its own word (or,
for phrases, as consecutive words) is blocked.
"""

import re

from fastapi import HTTPException, status

# Starter list - extend as needed. Keep entries lowercase; a phrase (e.g. "ass
# hole") is matched as consecutive words, not a substring.
BLOCKED_TERMS: set[str] = {
    "fuck",
    "fucking",
    "fucker",
    "motherfucker",
    "shit",
    "bullshit",
    "bitch",
    "asshole",
    "ass hole",
    "bastard",
    "cunt",
    "dick",
    "dickhead",
    "pussy",
    "whore",
    "slut",
    "nigger",
    "nigga",
    "faggot",
    "retard",
    "retarded",
    "douchebag",
    "twat",
    "wanker",
    "prick",
}

BLOCKED_MESSAGE = "This message was blocked because it contains foul language."

_MAX_PHRASE_WORDS = max((len(term.split()) for term in BLOCKED_TERMS), default=1)


def _normalize_word(word: str) -> str:
    """Strips punctuation used to break up a word (so "f.u.c.k" / "f_u_c_k"
    normalize to "fuck") and collapses 3+ repeated letters (so "fuuuck" ->
    "fuck"), without merging separate words together."""
    stripped = re.sub(r"[\-_.,!*'\"]+", "", word)
    return re.sub(r"(.)\1{2,}", r"\1", stripped)


def _tokenize(text: str) -> list[str]:
    words = [w for w in re.split(r"\s+", text.lower().strip()) if w]
    normalized = [_normalize_word(w) for w in words]
    # Merge runs of single-character tokens ("f u c k" -> "fuck") so spaced-out
    # obfuscation is still caught, without affecting normal multi-letter words.
    merged: list[str] = []
    i = 0
    while i < len(normalized):
        if len(normalized[i]) == 1:
            run = normalized[i]
            j = i + 1
            while j < len(normalized) and len(normalized[j]) == 1:
                run += normalized[j]
                j += 1
            merged.append(run)
            i = j
        else:
            merged.append(normalized[i])
            i += 1
    return [w for w in merged if w]


def contains_profanity(text: str) -> bool:
    if not text:
        return False
    words = _tokenize(text)
    if not words:
        return False
    for size in range(1, _MAX_PHRASE_WORDS + 1):
        for i in range(len(words) - size + 1):
            if " ".join(words[i : i + size]) in BLOCKED_TERMS:
                return True
    return False


def assert_no_profanity(text: str) -> None:
    """Raises a 400 HTTPException if `text` contains any blocked word/phrase."""
    if contains_profanity(text):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, BLOCKED_MESSAGE)
