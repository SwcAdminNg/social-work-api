"""Text embeddings for the semantic answer cache and for picking relevant passages.

With an OpenAI key, questions are embedded with `jad_ai_embedding_model` (256
dimensions, which keeps vectors small and comparisons fast). Without one, or if the
call fails, a built-in lexical embedding is used: stemmed words, word pairs and
character n-grams hashed into 256 dimensions. It needs no service and catches
rewordings like "summarise this" / "give me a summary of this".

Vectors are only ever compared with vectors of the same `kind`.
"""

import hashlib
import logging
import math
import re
from array import array

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

DIMS = 256
LOCAL_KIND = "local-hash-v1"

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "am", "do", "does", "did", "of", "to", "in",
    "on", "for", "with", "about", "and", "or", "this", "that", "these", "those", "it", "its", "me", "my", "i",
    "you", "your", "we", "our", "us", "can", "could", "would", "will", "shall", "should", "please", "kindly",
    "give", "tell", "help", "let", "s", "some", "any", "from", "by", "as", "at", "into", "so", "just", "also",
    "what", "which", "lesson", "document", "material", "module", "here", "there", "really", "briefly", "quick", "quickly",
}
# Same idea, different words. Applied before stemming.
_SYNONYMS = {
    "summarise": "summary", "summarize": "summary", "summarised": "summary", "summarized": "summary",
    "summarising": "summary", "summarizing": "summary", "recap": "summary", "overview": "summary",
    "tldr": "summary", "gist": "summary", "outline": "summary",
    "explain": "explain", "describe": "explain", "clarify": "explain", "elaborate": "explain",
    "meaning": "define", "means": "define", "mean": "define", "definition": "define", "define": "define",
    "examples": "example", "instance": "example", "illustration": "example",
    "test": "quiz", "questions": "quiz", "practice": "quiz", "quiz": "quiz",
    "important": "key", "main": "key", "major": "key", "crucial": "key", "essential": "key",
    "points": "point", "ideas": "point", "takeaways": "point", "takeaway": "point",
    "difference": "differ", "differences": "differ", "different": "differ", "distinguish": "differ",
    "simple": "simple", "simply": "simple", "easy": "simple", "plain": "simple",
    "whats": "what", "what's": "what", "hows": "how", "how's": "how",
}
_NEGATIONS = {"not", "no", "never", "without", "isnt", "arent", "dont", "doesnt", "cant", "wont", "shouldnt"}


def _tokens(text: str) -> list[str]:
    text = text.lower().replace("’", "'")
    text = re.sub(r"n't\b", " not", text)
    words = re.findall(r"[a-z0-9']+", text)
    out = []
    for word in words:
        word = word.strip("'")
        if not word:
            continue
        word = _SYNONYMS.get(word, word)
        if len(word) > 5 and word not in _STOPWORDS:
            for suffix in ("ations", "ation", "ments", "ment", "ings", "ing", "ness", "ies", "ed", "es", "ly", "s"):
                if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                    word = word[: -len(suffix)]
                    break
        out.append(word)
    return out


def content_words(text: str) -> list[str]:
    return [t for t in _tokens(text) if t not in _STOPWORDS]


def normalize_question(text: str) -> str:
    """Canonical form for exact matching: same words in the same order."""
    return " ".join(content_words(text)) or text.strip().lower()


def _bucket(feature: str) -> tuple[int, float]:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "little")
    return value % DIMS, (1.0 if (value >> 40) & 1 else -1.0)


def local_vector(text: str) -> list[float]:
    words = content_words(text)
    vec = [0.0] * DIMS
    features: list[tuple[str, float]] = [(f"w:{w}", 1.0) for w in words]
    features += [(f"b:{a}_{b}", 0.6) for a, b in zip(words, words[1:])]
    for word in words:
        padded = f"#{word}#"
        features += [(f"c:{padded[i:i + 4]}", 0.25) for i in range(max(len(padded) - 3, 1))]
    for feature, weight in features:
        index, sign = _bucket(feature)
        vec[index] += sign * weight
    return _unit(vec)


def _unit(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def pack(vec: list[float]) -> bytes:
    return array("f", vec).tobytes()


def unpack(data: bytes) -> list[float]:
    values = array("f")
    values.frombytes(data)
    return values.tolist()


def threshold(kind: str) -> float:
    """How close two questions must be to share an answer."""
    return 0.82 if kind == LOCAL_KIND else 0.90


def same_intent(a: str, b: str) -> bool:
    """Guards a similarity match: a negation or a number on one side only
    ("what is X" vs "what is not X", "step 2" vs "step 3") means a different question."""
    ta, tb = set(_tokens(a)), set(_tokens(b))
    if bool(ta & _NEGATIONS) != bool(tb & _NEGATIONS):
        return False
    return {t for t in ta if t.isdigit()} == {t for t in tb if t.isdigit()}


async def embed(text: str) -> tuple[str, list[float]]:
    if settings.openai_api_key and settings.jad_ai_embedding_model:
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                response = await client.post(
                    f"{settings.openai_api_base_url.rstrip('/')}/embeddings",
                    headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                    json={"model": settings.jad_ai_embedding_model, "input": text[:2000], "dimensions": DIMS},
                )
                response.raise_for_status()
            vector = response.json()["data"][0]["embedding"]
            return f"openai:{settings.jad_ai_embedding_model}:{DIMS}", _unit([float(v) for v in vector])
        except Exception as exc:  # noqa: BLE001 - the lexical vector is a fine fallback
            logger.warning("JAD AI embedding call failed, using the built-in one: %s", exc)
    return LOCAL_KIND, local_vector(text)
