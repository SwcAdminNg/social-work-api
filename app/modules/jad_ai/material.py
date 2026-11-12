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
