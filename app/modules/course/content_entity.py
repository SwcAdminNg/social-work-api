import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity


class VideoProviderEnum(str, enum.Enum):
    BUNNY = "BUNNY"


class VideoStatusEnum(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class CourseVideo(BaseEntity):
    __tablename__ = "course_videos"

    course_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_items.id"), unique=True, nullable=False, index=True
    )
    provider: Mapped[VideoProviderEnum] = mapped_column(
        Enum(VideoProviderEnum, name="video_provider_enum", native_enum=True),
        nullable=False,
        default=VideoProviderEnum.BUNNY,
    )
    bunny_video_guid: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[VideoStatusEnum] = mapped_column(
        Enum(VideoStatusEnum, name="video_status_enum", native_enum=True),
        nullable=False,
        default=VideoStatusEnum.PENDING,
    )
    playback_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CourseDocument(BaseEntity):
    __tablename__ = "course_documents"

    course_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_items.id"), unique=True, nullable=False, index=True
    )
    storage_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_uploaded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AssessmentTypeEnum(str, enum.Enum):
    """The set of pluggable assessment kinds. To add a new one: add a member here,
    a settings table keyed by `assessment_id` (see `CourseQuizSettings`/`CourseEssaySettings`),
    and branch on it in `CourseContentService`/`LearningService`."""

    QUIZ = "QUIZ"
    ESSAY = "ESSAY"
    QUIZ_GROUP = "QUIZ_GROUP"


class MultiAnswerModeEnum(str, enum.Enum):
    AND = "AND"
    OR = "OR"


class EssaySubmissionModeEnum(str, enum.Enum):
    TEXT = "TEXT"
    DOCUMENT = "DOCUMENT"


class CourseAssessment(BaseEntity):
    """Polymorphic parent row for a course item's assessment. The actual settings
    live in a type-specific table (`CourseQuizSettings`/`CourseEssaySettings`) keyed
    by `assessment_id`, matching the `course_item_id`-keyed pattern used by
    `CourseVideo`/`CourseDocument`."""

    __tablename__ = "course_assessments"

    course_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_items.id"), unique=True, nullable=False, index=True
    )
    assessment_type: Mapped[AssessmentTypeEnum] = mapped_column(
        Enum(AssessmentTypeEnum, name="assessment_type_enum", native_enum=True), nullable=False
    )
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # At most one per CourseSection (enforced in the service layer, not the DB - see
    # CourseContentService._ensure_single_final_assessment_per_section). Marks this
    # assessment as the gate a student must pass to unlock the section's items to
    # unlock the *next* CourseSection. The one on the course's *last* section doubles
    # as the course-wide final exam: passing it completes the course, exhausting its
    # retries without passing resets the *entire* course instead of just one section.
    is_final_assessment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CourseQuizSettings(BaseEntity):
    __tablename__ = "course_quiz_settings"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_assessments.id"), unique=True, nullable=False, index=True
    )
    max_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pass_mark_percentage: Mapped[int] = mapped_column(Integer, nullable=False, default=70)
    show_result_to_student: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CourseEssaySettings(BaseEntity):
    __tablename__ = "course_essay_settings"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_assessments.id"), unique=True, nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    submission_mode: Mapped[EssaySubmissionModeEnum] = mapped_column(
        Enum(EssaySubmissionModeEnum, name="essay_submission_mode_enum", native_enum=True), nullable=False
    )
    # Only meaningfully enforced when this essay is a final assessment (see
    # CourseAssessment.is_final_assessment) - a regular essay has nothing that
    # "fails" it. Mirrors CourseQuizSettings' fields so pass/fail and retry
    # semantics work the same way across all three assessment types.
    pass_mark_percentage: Mapped[int] = mapped_column(Integer, nullable=False, default=70)
    max_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CourseQuizGroupSettings(BaseEntity):
    """Settings for a QUIZ_GROUP assessment - a set of named sections (each its own
    nested quiz with its own question pool), taken together in one sitting with a
    single overall score. Mirrors `CourseQuizSettings` plus an optional timer."""

    __tablename__ = "course_quiz_group_settings"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_assessments.id"), unique=True, nullable=False, index=True
    )
    max_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pass_mark_percentage: Mapped[int] = mapped_column(Integer, nullable=False, default=70)
    show_result_to_student: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Null = untimed. Otherwise the attempt auto-submits (scoring whatever was
    # saved) once `started_at + time_limit_seconds` has passed.
    time_limit_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CourseQuizGroupSection(BaseEntity):
    """One nested quiz within a QUIZ_GROUP - a named pool of questions. On each
    attempt, `questions_to_ask` of them are drawn at random (favoring questions the
    student hasn't seen yet on prior attempts); null/0 means "ask all of them"."""

    __tablename__ = "course_quiz_group_sections"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_assessments.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    questions_to_ask: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CourseQuizQuestion(BaseEntity):
    __tablename__ = "course_quiz_questions"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_assessments.id"), nullable=False, index=True
    )
    # Set only for questions that belong to a QUIZ_GROUP section's pool (in which
    # case `assessment_id` points at the group, not a standalone QUIZ). Null for
    # ordinary standalone-quiz questions.
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_quiz_group_sections.id"), nullable=True, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    allow_multiple_answers: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    multi_answer_mode: Mapped[MultiAnswerModeEnum | None] = mapped_column(
        Enum(MultiAnswerModeEnum, name="multi_answer_mode_enum", native_enum=True), nullable=True
    )


class CourseQuizOption(BaseEntity):
    __tablename__ = "course_quiz_options"

    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_quiz_questions.id"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
