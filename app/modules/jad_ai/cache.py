"""Semantic answer cache for JAD AI.

Only stand-alone questions are cached: the first question of a chat, or a tapped
suggestion. A question asked mid-conversation depends on what came before, so it
always goes to the model.

Lookup, cheapest first:
1. Redis, by exact (normalised) wording            -> one primary-key read
2. Postgres, by exact wording                      -> one indexed read
3. By meaning: the question's embedding against the lesson's cached questions
   (their vectors are kept in Redis for an hour, so this is usually one Redis
   read plus a few thousand multiplications), guarded so "X" never matches
   "not X" and "step 2" never matches "step 3".

Entries are scoped to one lesson version (`context_key`), so editing or
re-uploading a lesson, changing the quiz question or the prompt starts fresh.
"""

import base64
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache as redis_cache
from app.core.config import settings
from app.modules.jad_ai.embeddings import cosine, embed, normalize_question, pack, same_intent, threshold, unpack
from app.modules.jad_ai.entity import JadCacheEntry
from app.modules.jad_ai.material import sha

logger = logging.getLogger(__name__)

CANDIDATE_LIMIT = 400
CANDIDATES_TTL = 3600
ANSWER_TTL = 24 * 3600


@dataclass
class CacheHit:
    entry_id: uuid.UUID
    answer: str
    suggestions: list[str]
    similarity: float


@dataclass
class Lookup:
    question_hash: str
    kind: str
    vector: list[float]
    hit: CacheHit | None = None


def _exact_key(context_key: str, question_hash: str) -> str:
    return f"jad:x:{context_key}:{question_hash}"


def _candidates_key(item_id: uuid.UUID, context_key: str, kind: str) -> str:
    return f"jad:c:{item_id}:{context_key}:{kind}"


class SemanticCache:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _fresh_after(self) -> datetime:
        return datetime.now(timezone.utc) - timedelta(days=settings.jad_ai_cache_days)

    async def lookup(self, item_id: uuid.UUID, context_key: str, question: str) -> Lookup:
        question_hash = sha(normalize_question(question))

        cached_id = await redis_cache.get_cache(_exact_key(context_key, question_hash))
        if cached_id:
            # Checked against the database so an evicted answer is never served.
            entry = await self.session.get(JadCacheEntry, uuid.UUID(cached_id))
            if entry is not None and entry.deleted_at is None:
                hit = CacheHit(entry.id, entry.answer, entry.suggestions or [], 1.0)
                return Lookup(question_hash, entry.embedding_kind, [], hit)
            await redis_cache.delete_cache(_exact_key(context_key, question_hash))

        exact = (
            await self.session.execute(
                select(JadCacheEntry)
                .where(
                    JadCacheEntry.item_id == item_id,
                    JadCacheEntry.context_key == context_key,
                    JadCacheEntry.question_hash == question_hash,
                    JadCacheEntry.deleted_at.is_(None),
                    JadCacheEntry.created_at >= self._fresh_after(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if exact is not None:
            hit = CacheHit(exact.id, exact.answer, exact.suggestions or [], 1.0)
            await self._remember_exact(context_key, question_hash, hit)
            return Lookup(question_hash, exact.embedding_kind, unpack(exact.embedding), hit)

        kind, vector = await embed(question)
        best: tuple[float, str, str] | None = None
        for entry_id, entry_question, entry_vector in await self._candidates(item_id, context_key, kind):
            score = cosine(vector, entry_vector)
            if score >= threshold(kind) and (best is None or score > best[0]) and same_intent(question, entry_question):
                best = (score, entry_id, entry_question)

        lookup = Lookup(question_hash, kind, vector)
        if best is not None:
            entry = await self.session.get(JadCacheEntry, uuid.UUID(best[1]))
            if entry is not None and entry.deleted_at is None:
                lookup.hit = CacheHit(entry.id, entry.answer, entry.suggestions or [], best[0])
                # Next time this exact wording skips the embedding too.
                await self._remember_exact(context_key, question_hash, lookup.hit)
        return lookup

    async def _candidates(self, item_id: uuid.UUID, context_key: str, kind: str) -> list[tuple[str, str, list[float]]]:
        key = _candidates_key(item_id, context_key, kind)
        cached = await redis_cache.get_cache(key)
        if cached is not None:
            return [(c[0], c[1], unpack(base64.b64decode(c[2]))) for c in cached]

        rows = (
            await self.session.execute(
                select(JadCacheEntry.id, JadCacheEntry.question, JadCacheEntry.embedding)
                .where(
                    JadCacheEntry.item_id == item_id,
                    JadCacheEntry.context_key == context_key,
                    JadCacheEntry.embedding_kind == kind,
                    JadCacheEntry.deleted_at.is_(None),
                    JadCacheEntry.created_at >= self._fresh_after(),
                )
                .order_by(JadCacheEntry.hit_count.desc(), JadCacheEntry.created_at.desc())
                .limit(CANDIDATE_LIMIT)
            )
        ).all()
        await redis_cache.set_cache(
            key,
            [[str(r.id), r.question, base64.b64encode(r.embedding).decode()] for r in rows],
            expire=CANDIDATES_TTL,
        )
        return [(str(r.id), r.question, unpack(r.embedding)) for r in rows]

    async def _remember_exact(self, context_key: str, question_hash: str, hit: CacheHit) -> None:
        await redis_cache.set_cache(_exact_key(context_key, question_hash), str(hit.entry_id), expire=ANSWER_TTL)

    async def record_hit(self, entry_id: uuid.UUID) -> None:
        await self.session.execute(
            update(JadCacheEntry)
            .where(JadCacheEntry.id == entry_id)
            .values(hit_count=JadCacheEntry.hit_count + 1, last_hit_at=datetime.now(timezone.utc))
        )

    async def store(
        self,
        *,
        item_id: uuid.UUID,
        context_key: str,
        question: str,
        lookup: Lookup,
        answer: str,
        suggestions: list[str],
    ) -> JadCacheEntry:
        if not lookup.vector:
            lookup.kind, lookup.vector = await embed(question)
        entry = JadCacheEntry(
            item_id=item_id,
            context_key=context_key,
            question=question[:2000],
            question_hash=lookup.question_hash,
            embedding_kind=lookup.kind,
            embedding=pack(lookup.vector),
            answer=answer,
            suggestions=suggestions,
        )
        self.session.add(entry)
        await self.session.flush()
        await redis_cache.delete_cache(_candidates_key(item_id, context_key, lookup.kind))
        return entry

    async def evict(self, entry_id: uuid.UUID) -> None:
        """Retire an answer (e.g. after a thumbs-down) so the next asker gets a fresh one."""
        entry = await self.session.get(JadCacheEntry, entry_id)
        if entry is None or entry.deleted_at is not None:
            return
        entry.mark_deleted()
        await self.session.flush()
        await redis_cache.delete_cache(_candidates_key(entry.item_id, entry.context_key, entry.embedding_kind))
        await redis_cache.delete_cache(_exact_key(entry.context_key, entry.question_hash))
