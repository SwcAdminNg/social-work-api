"""JAD AI: who may ask what, where the answer comes from, and what is kept.

Available on DOCUMENT and SCORM lessons and on practice quizzes (a QUIZ that is
not the module's final assessment). Never on scored final assessments.

A turn, in order:
1. Checks: enrolled, lesson unlocked, lesson type allowed, within usage limits.
2. The question is cleaned; an obvious prompt-injection attempt gets a fixed reply
   and never reaches the model.
3. A stand-alone question (first in the chat, or a tapped suggestion) is looked up
   in the semantic cache; a hit is answered instantly with no tokens.
4. Otherwise DeepSeek streams the answer, grounded in the lesson's text. The answer
   is checked for prompt leaks as it streams, and a clean, complete stand-alone
   answer is added to the cache for the next learner.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache as redis_cache
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.storage import get_r2_client
from app.modules.course.content_entity import AssessmentTypeEnum, VideoStatusEnum
from app.modules.course.entity import CourseItemTypeEnum
from app.modules.jad_ai import guard, llm
from app.modules.jad_ai.cache import CacheHit, Lookup, SemanticCache
from app.modules.jad_ai.dto import JadAskDTO, JadMessageDTO, JadStateDTO
from app.modules.jad_ai.entity import JadConversation, JadItemContext, JadMessage
from app.modules.jad_ai.material import MAX_FILE_BYTES, extract_document_text, html_to_text, select_passages, sha
from app.modules.jad_ai.prompt import (
    DEFAULT_SUGGESTIONS,
    PROMPT_VERSION,
    STARTER_SYSTEM,
    FollowupSplitter,
    build_system_prompt,
    clean_suggestions,
    starter_request,
)
from app.modules.learning.service import LearningService
from app.modules.user.entity import User

logger = logging.getLogger(__name__)

HISTORY_TURNS = 8
HISTORY_CHARS = 1500
QUIZ_SIBLING_LESSONS = 4
UNAVAILABLE = "JAD AI isn't available for this lesson"


@dataclass
class LessonScope:
    item: object
    course: object
    section: object
    kind: str  # "document" | "scorm" | "quiz"
    assessment: object | None = None


@dataclass
class PreparedTurn:
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    user_message_id: uuid.UUID
    item_id: uuid.UUID
    lesson_title: str
    question: str
    question_id: uuid.UUID | None
    context_key: str = ""
    messages: list[dict[str, str]] = field(default_factory=list)
    canary: str = ""
    fence: str = ""
    blocked: bool = False
    cacheable: bool = False
    lookup: Lookup | None = None
    hit: CacheHit | None = None


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class JadService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.learning = LearningService(session)
        self.content_repo = self.learning.content_repo

    # -- access -----------------------------------------------------------------

    async def _scope(self, user_id: uuid.UUID, course_id: uuid.UUID, item_id: uuid.UUID) -> LessonScope:
        if not await self.learning.repo.get_user_course_access(user_id, course_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not enrolled")
        item = await self.content_repo.get_item(item_id)
        sections = await self.content_repo.list_sections(course_id)
        section = next((s for s in sections if item is not None and s.id == item.section_id), None)
        if item is None or section is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
        await self.learning._ensure_section_unlocked(user_id, course_id, item.section_id)

        course = await self.learning.course_repo.get_by_id(course_id)
        if item.item_type == CourseItemTypeEnum.DOCUMENT:
            return LessonScope(item, course, section, "document")
        if item.item_type == CourseItemTypeEnum.SCORM:
            return LessonScope(item, course, section, "scorm")
        if item.item_type == CourseItemTypeEnum.ASSESSMENT:
            assessment = await self.content_repo.get_assessment_by_item(item.id)
            if assessment is not None and assessment.assessment_type == AssessmentTypeEnum.QUIZ:
                if assessment.is_final_assessment:
                    raise HTTPException(status.HTTP_403_FORBIDDEN, "JAD AI isn't available on scored assessments")
                return LessonScope(item, course, section, "quiz", assessment)
        raise HTTPException(status.HTTP_404_NOT_FOUND, UNAVAILABLE)

    # -- lesson text --------------------------------------------------------------

    async def _source(self, item) -> tuple[str, object] | None:
        """(source key, content row) for a lesson whose text can be read."""
        if item.item_type == CourseItemTypeEnum.DOCUMENT:
            doc = await self.content_repo.get_document_by_item(item.id)
            if doc is not None and doc.is_uploaded:
                return f"doc:{doc.storage_key}", doc
        elif item.item_type == CourseItemTypeEnum.SCORM:
            pkg = await self.content_repo.get_scorm_package_by_item(item.id)
            if pkg is not None and pkg.status == VideoStatusEnum.READY and pkg.extracted_prefix:
                return f"scorm:{pkg.extracted_prefix}{pkg.launch_path or 'index.html'}", pkg
        return None

    async def _context(self, item) -> JadItemContext | None:
        """The lesson's stored text, extracting it first if it is missing or stale."""
        source = await self._source(item)
        if source is None:
            return None
        source_key, row = source
        context = (
            await self.session.execute(select(JadItemContext).where(JadItemContext.item_id == item.id))
        ).scalar_one_or_none()
        if context is not None and context.source_key == source_key:
            return context

        material = await asyncio.to_thread(self._read_material, item.item_type, row)
        if context is None:
            context = JadItemContext(item_id=item.id, source_key=source_key, content_hash="", material="")
            self.session.add(context)
        context.source_key = source_key
        context.material = material
        context.content_hash = sha(f"{source_key}\n{material}")
        context.suggestions = None
        try:
            await self.session.commit()
        except IntegrityError:  # another request stored it first
            await self.session.rollback()
            context = (
                await self.session.execute(select(JadItemContext).where(JadItemContext.item_id == item.id))
            ).scalar_one_or_none()
        return context

    @staticmethod
    def _read_material(item_type, row) -> str:
        r2 = get_r2_client()
        try:
            if item_type == CourseItemTypeEnum.DOCUMENT:
                data = r2.read_bytes(row.storage_key, max_bytes=MAX_FILE_BYTES)
                return extract_document_text(row.file_name, row.mime_type, data)
            data = r2.read_bytes(f"{row.extracted_prefix}{row.launch_path or 'index.html'}", max_bytes=5 * 1024 * 1024)
            text = html_to_text(data.decode("utf-8", errors="ignore"))
            title = row.manifest_title or ""
            return f"{title}\n{text}".strip() if title and title not in text else text
        except Exception as exc:  # noqa: BLE001 - JAD still works from the titles
            logger.warning("JAD AI could not read lesson text for %s: %s", getattr(row, "course_item_id", "?"), exc)
            return ""

    async def _quiz_material(self, scope: LessonScope) -> tuple[str, str]:
        """For a practice quiz: the readings and activities in the same module."""
        items = await self.content_repo.list_items_for_sections([scope.section.id])
        lessons = [
            i for i in sorted(items, key=lambda i: i.order_index or 0)
            if i.item_type in (CourseItemTypeEnum.DOCUMENT, CourseItemTypeEnum.SCORM)
        ]
        before = [i for i in lessons if (i.order_index or 0) <= (scope.item.order_index or 0)]
        chosen = (before[-QUIZ_SIBLING_LESSONS:] or lessons[:QUIZ_SIBLING_LESSONS])
        parts, hashes = [], []
        for lesson in chosen:
            context = await self._context(lesson)
            if context is not None and context.material:
                parts.append(f"### {lesson.title}\n{context.material}")
                hashes.append(context.content_hash)
        return "\n\n".join(parts), sha("|".join(hashes))

    async def _quiz_question(self, user_id: uuid.UUID, scope: LessonScope, question_id: uuid.UUID) -> str | None:
        """The question as this learner sees it (reworded on a retry), without answers."""
        pending = await self.learning.repo.get_pending_quiz_version(user_id, scope.item.id)
        if pending is not None:
            for q in pending.presented_questions:
                if q.get("id") == str(question_id):
                    options = [o.get("text", "") for o in q.get("options", [])]
                    return _format_question(q.get("text", ""), options, bool(q.get("allow_multiple_answers")))
            return None
        question = await self.content_repo.get_question(question_id)
        if question is None or question.assessment_id != scope.assessment.id:
            return None
        options = await self.content_repo.list_options_for_questions([question.id])
        ordered = sorted(options, key=lambda o: o.order_index or 0)
        return _format_question(question.text, [o.text for o in ordered], question.allow_multiple_answers)

    # -- state ----------------------------------------------------------------------

    async def get_state(self, user: User, course_id: uuid.UUID, item_id: uuid.UUID) -> tuple[JadStateDTO, bool]:
        """The panel's starting state, and whether the lesson still needs warming up
        (its text read and starter questions written) in the background."""
        scope = await self._scope(user.id, course_id, item_id)
        conversation = await self._conversation(user.id, item_id)
        messages = []
        if conversation is not None:
            rows = (
                await self.session.execute(
                    select(JadMessage)
                    .where(JadMessage.conversation_id == conversation.id, JadMessage.deleted_at.is_(None))
                    .order_by(JadMessage.created_at.desc())
                    .limit(60)
                )
            ).scalars().all()
            messages = [_message_dto(m) for m in reversed(rows)]

        suggestions = DEFAULT_SUGGESTIONS[scope.kind]
        needs_warmup = False
        if scope.kind != "quiz":
            source = await self._source(scope.item)
            context = (
                await self.session.execute(select(JadItemContext).where(JadItemContext.item_id == item_id))
            ).scalar_one_or_none()
            fresh = context is not None and source is not None and context.source_key == source[0]
            if fresh and context.suggestions:
                suggestions = context.suggestions
            needs_warmup = source is not None and (not fresh or not context.suggestions)

        return (
            JadStateDTO(
                available=llm.is_configured(),
                lesson_kind=scope.kind,
                first_name=user.first_name,
                suggestions=suggestions,
                messages=messages,
                max_message_chars=settings.jad_ai_max_message_chars,
            ),
            needs_warmup and llm.is_configured(),
        )

    @staticmethod
    async def warm_up(item_id: uuid.UUID) -> None:
        """Background: read the lesson's text and write its starter questions, so the
        first question is fast and the pills are specific to the lesson."""
        lock_key = f"jad:warm:{item_id}"
        client = redis_cache.redis_client
        if client is not None:
            try:
                if not await client.set(lock_key, "1", nx=True, ex=120):
                    return
            except Exception:  # noqa: BLE001
                pass
        try:
            async with AsyncSessionLocal() as session:
                service = JadService(session)
                item = await service.content_repo.get_item(item_id)
                if item is None:
                    return
                context = await service._context(item)
                if context is None or context.suggestions:
                    return
                suggestions: list[str] = []
                if context.material:
                    try:
                        reply = await llm.json_chat(STARTER_SYSTEM, starter_request(item.title, context.material))
                        suggestions = clean_suggestions(reply.get("suggestions"), 6)
                        suggestions = [s for s in suggestions if not guard.is_injection(s)]
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("JAD AI starter questions failed for %s: %s", item_id, exc)
                kind = "document" if item.item_type == CourseItemTypeEnum.DOCUMENT else "scorm"
                context.suggestions = (suggestions + [s for s in DEFAULT_SUGGESTIONS[kind] if s not in suggestions])[:6] \
                    if len(suggestions) >= 3 else DEFAULT_SUGGESTIONS[kind]
                await session.commit()
        except Exception as exc:  # noqa: BLE001 - warming up is best effort
            logger.warning("JAD AI warm-up failed for %s: %s", item_id, exc)

    async def _conversation(self, user_id: uuid.UUID, item_id: uuid.UUID) -> JadConversation | None:
        return (
            await self.session.execute(
                select(JadConversation).where(JadConversation.user_id == user_id, JadConversation.item_id == item_id)
            )
        ).scalar_one_or_none()

    # -- usage limits ---------------------------------------------------------------

    async def _check_limits(self, user_id: uuid.UUID) -> None:
        now = datetime.now(timezone.utc)
        limits = (
            ("hour", settings.jad_ai_hourly_limit, timedelta(hours=1), now.strftime("%Y%m%d%H")),
            ("day", settings.jad_ai_daily_limit, timedelta(days=1), now.strftime("%Y%m%d")),
        )
        client = redis_cache.redis_client
        for name, limit, window, bucket in limits:
            if not limit:
                continue
            count = None
            if client is not None:
                try:
                    key = f"jad:rl:{name}:{user_id}:{bucket}"
                    count = await client.incr(key)
                    if count == 1:
                        await client.expire(key, int(window.total_seconds()) + 60)
                except Exception:  # noqa: BLE001 - fall back to counting in the database
                    count = None
            if count is None:
                count = 1 + (
                    await self.session.execute(
                        select(func.count(JadMessage.id)).where(
                            JadMessage.user_id == user_id,
                            JadMessage.role == "user",
                            JadMessage.created_at >= now - window,
                        )
                    )
                ).scalar_one()
            if count > limit:
                when = "in an hour" if name == "hour" else "tomorrow"
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    f"You've reached JAD AI's limit for now. You can ask again {when}.",
                )

    # -- a turn -----------------------------------------------------------------------

    async def prepare_turn(
        self, user: User, course_id: uuid.UUID, item_id: uuid.UUID, payload: JadAskDTO
    ) -> PreparedTurn:
        scope = await self._scope(user.id, course_id, item_id)
        if not llm.is_configured():
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "JAD AI is not available right now")
        question = guard.clean_input(payload.message, settings.jad_ai_max_message_chars)
        if not question:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ask a question")
        await self._check_limits(user.id)
        blocked = guard.is_injection(question)
        question_id = payload.question_id if scope.kind == "quiz" else None

        # Lesson text first: reading it may commit, so nothing of this turn is pending yet.
        material, material_hash, question_block = "", "none", None
        if not blocked:
            if scope.kind == "quiz":
                material, material_hash = await self._quiz_material(scope)
                if question_id is not None:
                    question_block = await self._quiz_question(user.id, scope, question_id)
            else:
                context = await self._context(scope.item)
                if context is not None:
                    material, material_hash = context.material, context.content_hash

        conversation = await self._conversation(user.id, item_id)
        if conversation is None:
            conversation = JadConversation(user_id=user.id, course_id=course_id, item_id=item_id)
            self.session.add(conversation)
            try:
                await self.session.commit()
            except IntegrityError:
                await self.session.rollback()
                conversation = await self._conversation(user.id, item_id)

        history = list(reversed((
            await self.session.execute(
                select(JadMessage)
                .where(
                    JadMessage.conversation_id == conversation.id,
                    JadMessage.deleted_at.is_(None),
                    JadMessage.blocked.is_(False),
                )
                .order_by(JadMessage.created_at.desc())
                .limit(HISTORY_TURNS)
            )
        ).scalars().all()))

        user_message = JadMessage(
            conversation_id=conversation.id, user_id=user.id, role="user", content=question,
            question_id=question_id, blocked=blocked,
        )
        self.session.add(user_message)
        await self.session.flush()
        turn = PreparedTurn(
            user_id=user.id,
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            item_id=item_id,
            lesson_title=scope.item.title,
            question=question,
            question_id=question_id,
            blocked=blocked,
        )
        if blocked:
            await self.session.commit()
            return turn

        lesson_hash = sha(f"{scope.item.title}\n{scope.item.item_description or ''}\n{scope.section.title}")
        turn.context_key = sha(
            "|".join([PROMPT_VERSION, scope.kind, material_hash, lesson_hash, sha(question_block or "")])
        )
        parts = build_system_prompt(
            kind=scope.kind,
            course_title=scope.course.title if scope.course else "",
            module_title=scope.section.title,
            lesson_title=scope.item.title,
            lesson_description=scope.item.item_description or "",
            material=select_passages(material, question),
            question_block=question_block,
            seed=turn.context_key,
        )
        turn.canary, turn.fence = parts.canary, parts.fence

        messages = [{"role": "system", "content": parts.system}]
        for message in [*history, user_message]:
            content = message.content[:HISTORY_CHARS] if message is not user_message else question
            if messages[-1]["role"] == message.role:
                # An unanswered question (stopped early) next to a new one: merge them.
                messages[-1]["content"] += "\n\n" + content
            else:
                messages.append({"role": message.role, "content": content})
        turn.messages = messages
        await self.session.commit()

        # Only stand-alone questions are shared through the cache.
        turn.cacheable = (not history or payload.from_suggestion) and not guard.has_personal_data(question)
        if turn.cacheable:
            try:
                turn.lookup = await SemanticCache(self.session).lookup(item_id, turn.context_key, question)
                turn.hit = turn.lookup.hit
            except Exception as exc:  # noqa: BLE001 - a cache problem must never block an answer
                logger.warning("JAD AI cache lookup failed: %s", exc)
                turn.lookup = None
        return turn

    async def stream_turn(self, turn: PreparedTurn) -> AsyncIterator[str]:
        if turn.blocked:
            reply = guard.BLOCKED_REPLY.format(title=turn.lesson_title)
            yield sse("start", {"cached": False})
            yield sse("delta", {"t": reply})
            message_id = await _persist(turn, reply, [], blocked=True)
            yield sse("done", {"message_id": str(message_id), "suggestions": [], "cached": False})
            return

        if turn.hit is not None:
            yield sse("start", {"cached": True})
            yield sse("delta", {"t": turn.hit.answer})
            message_id = await _persist(turn, turn.hit.answer, turn.hit.suggestions, cache_hit=turn.hit)
            yield sse("done", {"message_id": str(message_id), "suggestions": turn.hit.suggestions, "cached": True})
            return

        yield sse("start", {"cached": False})
        splitter = FollowupSplitter()
        result = llm.StreamResult()
        answer = ""
        withheld = False
        try:
            async for piece in llm.stream_chat(turn.messages, result):
                text = splitter.feed(piece)
                if not text:
                    continue
                answer += text
                if guard.leaks_prompt(answer, turn.canary, turn.fence):
                    withheld = True
                    break
                yield sse("delta", {"t": text})
            rest, suggestions = splitter.finish()
            if not withheld and rest:
                answer += rest
                if guard.leaks_prompt(answer, turn.canary, turn.fence):
                    withheld = True
                else:
                    yield sse("delta", {"t": rest})
        except asyncio.CancelledError:
            # The learner stopped it or left: keep what they saw.
            if answer.strip() and not withheld:
                asyncio.get_running_loop().create_task(_persist(turn, answer, [], result=result))
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("JAD AI answer failed: %s", exc)
            if not answer.strip():
                await _discard_question(turn)
                yield sse("error", {"message": "JAD AI couldn't answer just now. Please try again."})
                return
            suggestions = []

        if withheld:
            answer, suggestions = guard.WITHHELD_REPLY.format(title=turn.lesson_title), []
            yield sse("replace", {"t": answer})

        complete = result.finish_reason == "stop" and not withheld
        message_id = await _persist(
            turn, answer.strip(), suggestions, result=result, store_in_cache=turn.cacheable and complete
        )
        yield sse("done", {"message_id": str(message_id), "suggestions": suggestions, "cached": False})

    # -- housekeeping ----------------------------------------------------------------

    async def clear(self, user: User, course_id: uuid.UUID, item_id: uuid.UUID) -> None:
        await self._scope(user.id, course_id, item_id)
        conversation = await self._conversation(user.id, item_id)
        if conversation is None:
            return
        rows = (
            await self.session.execute(
                select(JadMessage).where(JadMessage.conversation_id == conversation.id, JadMessage.deleted_at.is_(None))
            )
        ).scalars().all()
        for row in rows:
            row.mark_deleted(user.id)
        await self.session.commit()

    async def feedback(self, user: User, message_id: uuid.UUID, helpful: bool | None) -> None:
        message = await self.session.get(JadMessage, message_id)
        if message is None or message.user_id != user.id or message.role != "assistant" or message.deleted_at:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
        message.feedback = None if helpful is None else (1 if helpful else -1)
        if helpful is False and message.cache_entry_id is not None:
            # Don't hand a poorly rated answer to the next learner.
            await SemanticCache(self.session).evict(message.cache_entry_id)
        await self.session.commit()


def _format_question(text: str, options: list[str], multiple: bool) -> str:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    lines = [f"Question: {text}", "Choose all that apply." if multiple else "Choose one answer.", "Options:"]
    lines += [f"{letters[i] if i < 26 else i + 1}. {option}" for i, option in enumerate(options)]
    return "\n".join(lines)


def _message_dto(message: JadMessage) -> JadMessageDTO:
    return JadMessageDTO(
        id=message.id,
        role=message.role,
        content=message.content,
        suggestions=message.suggestions or [],
        feedback=message.feedback,
        created_at=message.created_at,
    )


async def _persist(
    turn: PreparedTurn,
    answer: str,
    suggestions: list[str],
    *,
    result: llm.StreamResult | None = None,
    cache_hit: CacheHit | None = None,
    blocked: bool = False,
    store_in_cache: bool = False,
) -> uuid.UUID:
    """Save the answer in its own session (the request's has closed by the time a
    stream finishes) and, for a clean stand-alone answer, share it via the cache."""
    async with AsyncSessionLocal() as session:
        cache = SemanticCache(session)
        entry_id = cache_hit.entry_id if cache_hit else None
        if cache_hit is not None:
            await cache.record_hit(cache_hit.entry_id)
        elif store_in_cache and answer:
            try:
                lookup = turn.lookup or Lookup(question_hash="", kind="", vector=[])
                if not lookup.question_hash:
                    from app.modules.jad_ai.embeddings import normalize_question

                    lookup.question_hash = sha(normalize_question(turn.question))
                entry = await cache.store(
                    item_id=turn.item_id,
                    context_key=turn.context_key,
                    question=turn.question,
                    lookup=lookup,
                    answer=answer,
                    suggestions=suggestions,
                )
                entry_id = entry.id
            except Exception as exc:  # noqa: BLE001
                logger.warning("JAD AI could not cache an answer: %s", exc)
                await session.rollback()
                cache = SemanticCache(session)
        message = JadMessage(
            conversation_id=turn.conversation_id,
            user_id=turn.user_id,
            role="assistant",
            content=answer or "…",
            suggestions=suggestions or None,
            question_id=turn.question_id,
            cached=cache_hit is not None,
            cache_entry_id=entry_id,
            blocked=blocked,
            model=None if (cache_hit or blocked) else llm.model_name(),
            prompt_tokens=result.prompt_tokens if result else None,
            cached_prompt_tokens=result.cached_prompt_tokens if result else None,
            completion_tokens=result.completion_tokens if result else None,
        )
        session.add(message)
        await session.commit()
        return message.id


async def _discard_question(turn: PreparedTurn) -> None:
    """A question that got no answer is taken out of the chat so a retry doesn't
    show it twice (it still counts towards the usage limit)."""
    async with AsyncSessionLocal() as session:
        message = await session.get(JadMessage, turn.user_message_id)
        if message is not None:
            message.mark_deleted()
            await session.commit()
