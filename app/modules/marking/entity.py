import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity


class LearnerResultStatusEnum(str, enum.Enum):
    """Framework section 12's learner result statuses, plus the marking-loop
    states the moderation workflow needs."""

    DRAFT_MARK = "DRAFT_MARK"
    AWAITING_MODERATION = "AWAITING_MODERATION"
    RETURNED_TO_MARKER = "RETURNED_TO_MARKER"
    MODERATED = "MODERATED"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"  # a later published mark replaced this one
    UNDER_APPEAL = "UNDER_APPEAL"  # reserved for the formal appeals phase


# Marking is in progress: the learner can't resubmit underneath the marker.
IN_PROGRESS_STATUSES = frozenset(
    {
        LearnerResultStatusEnum.DRAFT_MARK,
        LearnerResultStatusEnum.AWAITING_MODERATION,
        LearnerResultStatusEnum.RETURNED_TO_MARKER,
        LearnerResultStatusEnum.MODERATED,
        LearnerResultStatusEnum.APPROVED,
    }
)


class MarkRecommendationEnum(str, enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class EssayMark(BaseEntity):
    """One marking cycle of one essay attempt (framework 5.2). Append-only
    history: grading never overwrites an earlier mark - a re-mark after a
    resubmission is a new row, and publishing supersedes the previous one.

    Only a PUBLISHED mark is copied onto EssaySubmission (score/feedback/
    is_published), so draft and moderated marks can never unlock a module or
    reach the learner early."""

    __tablename__ = "essay_marks"
    __table_args__ = (Index("ix_essay_marks_status_course", "status", "course_id"),)

    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("essay_submissions.id"), nullable=False, index=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("course_items.id"), nullable=False, index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False, index=True)
    learner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[LearnerResultStatusEnum] = mapped_column(
        Enum(LearnerResultStatusEnum, name="learner_result_status_enum", native_enum=True), nullable=False
    )

    marker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation: Mapped[MarkRecommendationEnum | None] = mapped_column(
        Enum(MarkRecommendationEnum, name="mark_recommendation_enum", native_enum=True), nullable=True
    )
    submitted_for_moderation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    moderator_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    moderated_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    moderated_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    moderation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # The marker contests the moderator's amendment; a Course Lead / Lead
    # Assessor (APPROVE_RESULTS) settles the final mark.
    disputed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    dispute_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    final_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    final_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_note: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    published_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
