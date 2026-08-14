import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel

from app.common.base_dto import BaseDTO
from app.modules.course.content_entity import AssessmentTypeEnum, EssaySubmissionModeEnum, MultiAnswerModeEnum
from app.modules.course.dto import CourseReadDTO
from app.modules.course.entity import CourseItemTypeEnum


class EnrolledCourseDTO(CourseReadDTO):
    progress_percent: int
    is_completed: bool
    is_enrolled: bool = True


class LearningItemDTO(BaseDTO):
    id: uuid.UUID
    title: str
    item_type: CourseItemTypeEnum
    is_completed: bool
    estimated_minutes: int | None = None


class LearningSectionDTO(BaseDTO):
    id: uuid.UUID
    title: str
    items: list[LearningItemDTO]


class CourseCurriculumDTO(BaseDTO):
    course_id: uuid.UUID
    progress_percent: int
    is_completed: bool
    sections: list[LearningSectionDTO]


class QuizQuestionDTO(BaseDTO):
    id: uuid.UUID
    text: str
    allow_multiple_answers: bool
    multi_answer_mode: MultiAnswerModeEnum | None
    options: list[dict[str, Any]]  # id, text


class QuizAttemptDTO(BaseDTO):
    """A previous attempt. `score`/`passed`/`answers` are nulled out when the quiz's
    `show_result_to_student` setting is off - `result_visible` tells the client why."""

    score: float | None
    passed: bool | None
    answers: dict[uuid.UUID, list[uuid.UUID]] | None
    result_visible: bool


class EssaySubmissionDTO(BaseDTO):
    """The student's own view of their essay submission. `score`/`feedback` are only
    populated once the instructor sets `is_published=True`."""

    content_text: str | None
    document_file_name: str | None
    document_download_url: str | None
    submitted_at: datetime
    is_graded: bool
    is_published: bool
    score: float | None
    feedback: str | None


class LearningItemContentDTO(BaseDTO):
    id: uuid.UUID
    title: str
    item_type: CourseItemTypeEnum
    is_completed: bool
    estimated_minutes: int | None = None

    # Optional fields depending on item_type
    video_url: str | None = None
    document_url: str | None = None

    # Assessment - common
    assessment_type: AssessmentTypeEnum | None = None
    due_date: datetime | None = None

    # Assessment - quiz
    questions: list[QuizQuestionDTO] | None = None
    max_attempts: int | None = None
    attempts_used: int | None = None
    attempts_remaining: int | None = None
    pass_mark_percentage: int | None = None
    show_result_to_student: bool | None = None
    previous_attempt: QuizAttemptDTO | None = None

    # Assessment - essay
    essay_question: str | None = None
    essay_description: str | None = None
    essay_submission_mode: EssaySubmissionModeEnum | None = None
    essay_submission: EssaySubmissionDTO | None = None


class QuizSubmitDTO(BaseModel):
    answers: dict[uuid.UUID, list[uuid.UUID]]  # Question ID -> List of chosen Option IDs


class QuizResultDTO(BaseDTO):
    """`score`/`correct_answers` are nulled out (and `result_visible=False`) when the
    quiz's `show_result_to_student` setting is off - the submission still counts, the
    student just isn't shown how they did."""

    score: float | None
    passed: bool | None
    correct_answers: dict[uuid.UUID, list[uuid.UUID]] | None  # Question ID -> List of correct Option IDs
    result_visible: bool


class EssaySubmitTextDTO(BaseModel):
    content_text: str


class EssayUploadUrlRequestDTO(BaseModel):
    file_name: str


class EssayUploadUrlResponseDTO(BaseDTO):
    upload_url: str
    storage_key: str


class EssayDocumentFinalizeDTO(BaseModel):
    storage_key: str
    file_name: str
    mime_type: str | None = None


class UserAssessmentStatusEnum(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    SUBMITTED = "SUBMITTED"
    GRADED = "GRADED"


class UserAssessmentDTO(BaseDTO):
    """One row per assessment (quiz or essay) the user has access to, with their
    latest status. Quiz-only fields are null for essays and vice versa."""

    item_id: uuid.UUID
    title: str
    course_id: uuid.UUID
    course_title: str
    assessment_type: AssessmentTypeEnum
    due_date: datetime | None = None
    status: UserAssessmentStatusEnum
    score: float | None = None
    last_activity_at: datetime | None = None  # latest quiz attempt, or essay submission time

    # Quiz-only
    max_attempts: int | None = None
    attempts_used: int | None = None
    attempts_remaining: int | None = None
    pass_mark_percentage: int | None = None

    # Essay-only
    is_graded: bool | None = None
    is_published: bool | None = None


class AssessmentStatsDTO(BaseDTO):
    upcoming_count: int
    completed_count: int
    average_score_percentage: float | None = None
    retakes_available_count: int
