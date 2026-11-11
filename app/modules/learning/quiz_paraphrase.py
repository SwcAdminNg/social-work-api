"""Reworded quizzes for retries.

When a student takes a scored quiz again, every question and option is reworded
by DeepSeek (same meaning, same correct answers) and the options are reshuffled,
so a retry can't be passed by remembering the wording or the position of the
right answer. Question and option IDs never change, so scoring is untouched.

The version a student saw is stored on their attempt (`presented_questions`) so
admins and instructors can see exactly what was asked and what was chosen.
"""

import asyncio
import json
import logging
import random
import re
import uuid
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Questions per AI request. Smaller chunks run in parallel and keep each reply short.
CHUNK_SIZE = 12


def build_presented_questions(questions: list, options: list) -> list[dict[str, Any]]:
    """The quiz in its authored wording and option order, in the stored snapshot shape."""
    options_by_question: dict[uuid.UUID, list] = {}
    for option in options:
        options_by_question.setdefault(option.question_id, []).append(option)

    presented = []
    for question in questions:
        q_options = sorted(options_by_question.get(question.id, []), key=lambda o: o.order_index or 0)
        presented.append(
            {
                "id": str(question.id),
                "section_id": str(question.section_id) if getattr(question, "section_id", None) else None,
                "text": question.text,
                "original_text": question.text,
                "allow_multiple_answers": bool(question.allow_multiple_answers),
                "multi_answer_mode": question.multi_answer_mode.value if question.multi_answer_mode else None,
                "options": [
                    {
                        "id": str(option.id),
                        "text": option.text,
                        "original_text": option.text,
                        "is_correct": bool(option.is_correct),
                    }
                    for option in q_options
                ],
            }
        )
    return presented


async def reword_for_retry(
    presented: list[dict[str, Any]], *, course_title: str, item_title: str
) -> tuple[list[dict[str, Any]], bool, str | None]:
    """Shuffle the options and ask DeepSeek to reword everything.

    Returns (questions, paraphrased, model). If the AI is switched off, not
    configured or fails, the student still gets the quiz - shuffled, in the
    original wording - and `paraphrased` is False so staff can tell.
    """
    reworded = [dict(q, options=[dict(o) for o in q["options"]]) for q in presented]
    for question in reworded:
        random.shuffle(question["options"])

    if not settings.quiz_retry_paraphrase_enabled or not settings.deepseek_api_key or not reworded:
        return reworded, False, None

    model = (settings.quiz_paraphrase_model or settings.deepseek_model).strip()
    chunks = [reworded[i : i + CHUNK_SIZE] for i in range(0, len(reworded), CHUNK_SIZE)]
    results = await asyncio.gather(
        *(_reword_chunk(chunk, model=model, course_title=course_title, item_title=item_title) for chunk in chunks),
        return_exceptions=True,
    )

    changed = 0
    for chunk, result in zip(chunks, results):
        if isinstance(result, BaseException):
            logger.warning("Quiz paraphrase chunk failed: %s", result)
            continue
        changed += _apply_rewording(chunk, result)

    if changed == 0:
        return reworded, False, None
    return reworded, True, model


async def _reword_chunk(
    chunk: list[dict[str, Any]], *, model: str, course_title: str, item_title: str
) -> dict[str, Any]:
    source = [
        {
            "id": q["id"],
            "text": q["original_text"],
            "options": [
                {"id": o["id"], "text": o["original_text"], "is_correct": o["is_correct"]} for o in q["options"]
            ],
        }
        for q in chunk
    ]
    prompt = f"""
Reword this multiple-choice quiz for a student who is retaking it, so they cannot pass by memorising the old wording.

Course: {course_title}
Quiz: {item_title}

Rules:
- Rewrite every question and every option in new words. Change the sentence structure, not just a word or two.
- Keep exactly the same meaning, difficulty and facts. Do not add hints or make any option more or less obviously right.
- An option marked is_correct=true must stay correct and every other option must stay wrong.
- Keep names, numbers, dates, legal or technical terms, and phrases like "All of the above" accurate.
- Keep every "id" exactly as given. Return every question and every option.
- Use clear, plain English suitable for social work learners.

Return only JSON in this shape:
{{"questions": [{{"id": "...", "text": "...", "options": [{{"id": "...", "text": "..."}}]}}]}}

Quiz:
{json.dumps({"questions": source}, ensure_ascii=False)}
""".strip()

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are an expert assessment editor. Reply with valid JSON only, no markdown or commentary.",
            },
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.7,
    }
    url = f"{settings.deepseek_api_base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.deepseek_api_key}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=settings.gemini_timeout_seconds) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"] or ""
    return json.loads(_strip_json_fence(content))


def _apply_rewording(chunk: list[dict[str, Any]], result: dict[str, Any]) -> int:
    """Copy reworded text onto the chunk by id; anything missing keeps its original
    wording. Returns how many questions were reworded."""
    by_id = {}
    for item in result.get("questions") or []:
        if isinstance(item, dict) and item.get("id"):
            by_id[str(item["id"])] = item

    changed = 0
    for question in chunk:
        reply = by_id.get(question["id"])
        if not reply:
            continue
        text = _clean(reply.get("text"))
        option_texts = {
            str(o["id"]): _clean(o.get("text"))
            for o in reply.get("options") or []
            if isinstance(o, dict) and o.get("id")
        }
        if text:
            question["text"] = text
            changed += 1
        for option in question["options"]:
            new_text = option_texts.get(option["id"])
            if new_text:
                option["text"] = new_text
    return changed


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", value).strip() if isinstance(value, str) else ""


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()
