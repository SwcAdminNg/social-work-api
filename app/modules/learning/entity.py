import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity


class UserCourseProgress(BaseEntity):
    __tablename__ = "user_course_progress"
    __table_args__ = (UniqueConstraint("user_id", "course_id", name="uq_user_course_progress"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False, index=True
    )
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserItemProgress(BaseEntity):
    __tablename__ = "user_item_progress"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_items.id"), nullable=False, index=True
    )
    is_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QuizAttempt(BaseEntity):
    __tablename__ = "quiz_attempts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_items.id"), nullable=False, index=True
    )
    score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    answers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class QuizGroupAttemptStatusEnum(str, enum.Enum):
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"


class QuizGroupAttempt(BaseEntity):
    """A student's attempt at a QUIZ_GROUP assessment. Unlike `QuizAttempt` (which
    is created in one shot on submit), this row is created up front when the
    student starts the attempt, so that:
    - the randomly-drawn question set per section can be persisted (`selected_questions`)
      and stays stable across page reloads instead of reshuffling,
    - an optional timer (`expires_at`) can be enforced and the attempt can be
      auto-submitted/scored from whatever was last saved if the student runs out
      of time without submitting.
    """

    __tablename__ = "quiz_group_attempts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_items.id"), nullable=False, index=True
    )
    status: Mapped[QuizGroupAttemptStatusEnum] = mapped_column(
        Enum(QuizGroupAttemptStatusEnum, name="quiz_group_attempt_status_enum", native_enum=True),
        nullable=False,
        default=QuizGroupAttemptStatusEnum.IN_PROGRESS,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_submitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # {section_id_str: [question_id_str, ...]} - the questions drawn from each
    # section's pool for this specific attempt.
    selected_questions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # {question_id_str: [option_id_str, ...]} - saved incrementally while
    # IN_PROGRESS (see `save_progress`), then frozen once SUBMITTED.
    answers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # [{"section_id": ..., "title": ..., "earned_points": ..., "total_questions": ..., "score_percent": ...}, ...]
    section_scores: Mapped[list | None] = mapped_column(JSONB, nullable=True)


class EssaySubmission(BaseEntity):
    __tablename__ = "essay_submissions"
    __table_args__ = (UniqueConstraint("user_id", "item_id", name="uq_essay_submissions_user_item"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_items.id"), nullable=False, index=True
    )
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_storage_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    document_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    graded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Total number of times this submission has been graded. For a regular essay
    # this only ever reaches 1 (grading locks further resubmission). For a *final*
    # essay assessment, a failed grade (below CourseEssaySettings.pass_mark_percentage)
    # re-opens the submission for another attempt as long as this stays below
    # CourseEssaySettings.max_attempts - see LearningService._authorize_essay_submission.
    graded_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
