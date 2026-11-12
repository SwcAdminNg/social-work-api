import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, LargeBinary, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity


class JadConversation(BaseEntity):
    """One running conversation per learner per lesson."""

    __tablename__ = "jad_conversations"
    __table_args__ = (UniqueConstraint("user_id", "item_id", name="uq_jad_conversations_user_item"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_items.id", ondelete="CASCADE"), nullable=False, index=True
    )


class JadMessage(BaseEntity):
    """A turn in a conversation. Soft-deleted when the learner starts a new chat,
    so usage limits still count it."""

    __tablename__ = "jad_messages"
    __table_args__ = (Index("ix_jad_messages_user_created", "user_id", "created_at"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jad_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Follow-up questions offered after an assistant answer.
    suggestions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # The quiz question on screen when the learner asked (practice quizzes only).
    question_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Served from the answer cache rather than the model.
    cached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # The cache entry this answer came from or created (so a thumbs-down can evict it).
    cache_entry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Turned away by the prompt-injection guard without calling the model.
    blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 1 = helpful, -1 = not helpful.
    feedback: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)


class JadItemContext(BaseEntity):
    """A lesson's readable text, pulled out of its file once (not on every
    question), plus the starter questions shown as pills."""

    __tablename__ = "jad_item_contexts"

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_items.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # Storage key (or package prefix) the text came from; a re-upload changes it.
    source_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    material: Mapped[str] = mapped_column(Text, nullable=False, default="")
    suggestions: Mapped[list | None] = mapped_column(JSONB, nullable=True)


class JadCacheEntry(BaseEntity):
    """A shared answer to a stand-alone question about a lesson. Looked up by exact
    wording first, then by meaning (embedding similarity) within the same lesson
    and lesson version, so similar questions from other learners cost no tokens."""

    __tablename__ = "jad_cache_entries"
    __table_args__ = (Index("ix_jad_cache_lookup", "item_id", "context_key", "embedding_kind"),)

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_items.id", ondelete="CASCADE"), nullable=False
    )
    # Lesson version + quiz question + prompt version; any change misses the cache.
    context_key: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)  # float32 array
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    suggestions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
