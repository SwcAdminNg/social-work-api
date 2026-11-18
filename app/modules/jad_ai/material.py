"""Reading a lesson's text, and choosing which parts of it to send with a question.

Text is pulled out of the lesson file once and stored (JadItemContext), so a
question never re-downloads or re-parses a PDF. A short lesson is sent whole,
which keeps the prompt identical between questions and lets DeepSeek's own
prefix cache bill it at the cached rate; a long one is cut into passages and only
the ones closest to the question are sent.
"""

import hashlib
import html
import io
import json
import logging
import re

from docx import Document
from pypdf import PdfReader

from app.modules.jad_ai.embeddings import cosine, local_vector

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_MATERIAL_CHARS = 150_000
# Lessons up to this size are sent whole.
FULL_CONTEXT_CHARS = 16_000
CHUNK_CHARS = 1_200
TOP_PASSAGES = 8


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tidy(text: str) -> str:
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in (text or "").splitlines()]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()[:MAX_MATERIAL_CHARS]


def extract_document_text(file_name: str, mime_type: str | None, data: bytes) -> str:
    name = (file_name or "").lower()
    mime = (mime_type or "").split(";")[0].strip().lower()
    try:
        if name.endswith(".pdf") or mime == "application/pdf":
            reader = PdfReader(io.BytesIO(data))
            return tidy("\n".join(page.extract_text() or "" for page in reader.pages))
        if name.endswith(".docx") or "wordprocessingml" in mime:
            document = Document(io.BytesIO(data))
            parts = [p.text for p in document.paragraphs]
            for table in document.tables:
                for row in table.rows:
                    parts.append(" | ".join(cell.text for cell in row.cells))
            return tidy("\n".join(parts))
        if name.endswith((".html", ".htm")) or mime == "text/html":
            return html_to_text(data.decode("utf-8", errors="ignore"))
        if name.endswith((".txt", ".md", ".csv")) or mime.startswith("text/"):
            return tidy(data.decode("utf-8", errors="ignore"))
    except Exception as exc:  # noqa: BLE001 - an unreadable file just means less context
        logger.warning("JAD AI could not read %s: %s", file_name, exc)
    return ""


def html_to_text(markup: str) -> str:
    markup = re.sub(r"(?is)<(script|style|noscript|template|svg)\b.*?</\1>", " ", markup)
    markup = re.sub(r"(?is)<!--.*?-->", " ", markup)
    markup = re.sub(r"(?i)<\s*(br|/p|/div|/li|/h[1-6]|/tr|/section|/article)\s*/?>", "\n", markup)
    markup = re.sub(r"(?s)<[^>]+>", " ", markup)
    return tidy(html.unescape(markup))


# --- SCORM / interactive packages ----------------------------------------------
#
# Authoring tools keep most of an interactive lesson's words out of the visible
# markup: narration scripts, captions, click-to-reveal panels, scenario branches
# and activity feedback live in <script> blocks as JS/JSON data, e.g.
#   {"track": "c5-1", "vo": "S. Scan. What danger ...", "html": "<h3>S · Scan</h3>..."}
# html_to_text() drops every script, so on its own it leaves JAD with little more
# than the button labels. scorm_to_text() adds the prose found in those scripts.

_SCRIPT_RE = re.compile(r"(?is)<script\b[^>]*>(.*?)</script>")
# A string literal, optionally preceded by the key it is assigned to.
_LITERAL_RE = re.compile(
    r"""(?:["']?([A-Za-z_][\w-]*)["']?\s*:\s*)?("(?:[^"\\\n]|\\.){2,}"|'(?:[^'\\\n]|\\.){2,}')"""
)
# Keys whose values are lesson words even when short ("Scan", "Act now").
_TEXT_KEYS = {
    "vo", "voiceover", "narration", "transcript", "text", "html", "title", "heading", "subtitle",
    "label", "body", "content", "desc", "description", "summary", "prompt", "question", "q",
    "answer", "option", "options", "choice", "feedback", "explanation", "why", "reason",
    "correct", "incorrect", "right", "wrong", "hint", "tip", "note", "caption", "message",
    "statement", "scenario", "outcome", "result", "takeaway", "point", "detail",
}
# Keys that never hold lesson words (captions repeat the narration line by line).
_SKIP_KEYS = {
    "src", "href", "url", "track", "col", "color", "colour", "class", "classname", "id", "style",
    "type", "icon", "img", "image", "audio", "video", "poster", "font", "caps", "cues", "key",
    "mode", "version", "lang", "name", "role", "event",
}
_CODE_HINTS = re.compile(
    r"(=>|function\b|\breturn\b|\bvar\b|\bconst\b|\blet\b|===|!==|&&|\|\||\bnull\b|"
    r"\bundefined\b|document\.|window\.|\.(mp3|mp4|jpg|png|svg|woff2?|css|js)\b|"
    r"^[#.]?[a-z-]+\s*\{|\brgba?\(|\d+px\b|cmi\.|LMS[A-Z]\w+)"
)
# Player controls that appear on every screen and say nothing about the lesson.
_PLAYER_CHROME = {
    "back", "next", "pause", "play", "replay", "speed 1×", "read text", "captions", "menu",
    "start", "start from the beginning", "review the screens", "review this chapter",
    "check my answer", "choose…", "choose a category", "not heard yet", "open all five",
    "open all six", "well done",
}


def _decode_literal(raw: str) -> str:
    body = raw[1:-1]
    if raw[0] == "'":
        body = body.replace("\\'", "'").replace('"', '\\"')
    try:
        return json.loads(f'"{body}"')
    except ValueError:
        return body.replace("\\n", "\n").replace('\\"', '"').replace("\\/", "/")


def _is_lesson_text(value: str, key: str | None) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z'’-]*", value)
    if not words or _CODE_HINTS.search(value):
        return False
    letters = sum(ch.isalpha() for ch in value)
    if letters < 0.55 * len(value.replace(" ", "")):
        return False
    if key in _TEXT_KEYS:
        return len(words) >= 1 and len(value) >= 3
    # Unlabelled literal: only keep clear prose.
    return len(words) >= 5 and " " in value


def scorm_to_text(markup: str) -> str:
    """Visible text of a package's launch page plus the narration, panel, scenario
    and feedback text held in its scripts, without duplicates."""
    visible = html_to_text(markup)
    lines = [ln for ln in visible.splitlines() if ln.strip().lower() not in _PLAYER_CHROME]
    seen = "\n".join(lines).lower()
    extra: list[str] = []
    for script in _SCRIPT_RE.findall(markup):
        for key, raw in _LITERAL_RE.findall(script):
            k = (key or "").lower() or None
            if k in _SKIP_KEYS:
                continue
            value = _decode_literal(raw)
            if "<" in value and ">" in value:
                value = html_to_text(value)
            value = re.sub(r"\s+", " ", html.unescape(value)).strip()
            if not value or not _is_lesson_text(value, k):
                continue
            norm = value.lower()
            if norm in _PLAYER_CHROME or norm in seen:
                continue
            seen += "\n" + norm
            extra.append(value)
    text = "\n".join(lines)
    if extra:
        text += "\n\nNarration, activities and feedback:\n" + "\n".join(extra)
    return tidy(text)


def chunk(text: str) -> list[str]:
    """Split on paragraph boundaries into passages of about CHUNK_CHARS."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        while len(paragraph) > CHUNK_CHARS:
            cut = paragraph.rfind(" ", 0, CHUNK_CHARS)
            cut = cut if cut > CHUNK_CHARS // 2 else CHUNK_CHARS
            if current:
                chunks.append(current)
                current = ""
            chunks.append(paragraph[:cut].strip())
            paragraph = paragraph[cut:].strip()
        if len(current) + len(paragraph) + 1 > CHUNK_CHARS and current:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks


def select_passages(material: str, query: str) -> str:
    """The whole lesson when it is short; otherwise its opening plus the passages
    most like the question, kept in reading order."""
    if len(material) <= FULL_CONTEXT_CHARS:
        return material
    chunks = chunk(material)
    query_vec = local_vector(query)
    scored = sorted(
        ((cosine(query_vec, local_vector(c)), i) for i, c in enumerate(chunks)),
        reverse=True,
    )
    keep = {0} | {i for _, i in scored[:TOP_PASSAGES]}
    parts = []
    previous = -1
    for i in sorted(keep):
        if previous != -1 and i != previous + 1:
            parts.append("[...]")
        parts.append(chunks[i])
        previous = i
    return "\n\n".join(parts)
