import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

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
    # True when a previous section's final assessment hasn't been passed yet (see
    # ASSESSMENTS_STUDENT_API.md's module-gating section). A locked section's items
    # still list here (so you can render them, greyed out) but fetching/submitting
    # them 403s until it unlocks.
    is_locked: bool = False


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
    """The student's own view of their essay submission. `score`/`feedback`/`passed`
    are only populated once the instructor sets `is_published=True`."""

    content_text: str | None
    document_file_name: str | None
    document_download_url: str | None
    submitted_at: datetime
    is_graded: bool
    is_published: bool
    score: float | None
    feedback: str | None
    # Only meaningful (non-null) once published and for essays used as a final
    # assessment - `score >= pass_mark_percentage`. Null for a regular essay, since
    # there's nothing to pass/fail there.
    passed: bool | None = None


# ---------------------------------------------------------------------------
# Quiz group (nested quizzes) - student side
# ---------------------------------------------------------------------------


class QuizGroupSectionOverviewDTO(BaseDTO):
    """Section metadata shown before an attempt starts. No questions here - the
    pool is only revealed once an attempt is started/resumed, so it can't be
    studied ahead of time and each attempt can draw a different subset."""

    id: uuid.UUID
    title: str
    order_index: int
    question_count: int  # how many questions this section will actually ask


class QuizGroupSectionAttemptDTO(BaseDTO):
    """One section's drawn questions for a specific (started) attempt."""

    section_id: uuid.UUID
    title: str
    questions: list[QuizQuestionDTO]


class QuizGroupActiveAttemptDTO(BaseDTO):
    """The in-progress attempt, returned by start/resume and embedded in the
    item-content response so a page reload picks up exactly where it left off -
    same drawn questions, same timer, same saved answers."""

    attempt_id: uuid.UUID
    started_at: datetime
    expires_at: datetime | None
    sections: list[QuizGroupSectionAttemptDTO]
    saved_answers: dict[uuid.UUID, list[uuid.UUID]]


class QuizGroupSectionResultDTO(BaseDTO):
    section_id: uuid.UUID
    title: str
    earned_points: float
    total_questions: int
    score_percent: float


class QuizGroupResultDTO(BaseDTO):
    """`score`/`sections`/`correct_answers` are nulled out (and `result_visible=False`)
    when the group's `show_result_to_student` setting is off - the submission still
    counts, the student just isn't shown how they did. `auto_submitted` is true when
    the attempt was finalized because the timer ran out rather than by explicit
    submission."""

    attempt_id: uuid.UUID
    score: float | None
    passed: bool | None
    auto_submitted: bool
    sections: list[QuizGroupSectionResultDTO] | None
    correct_answers: dict[uuid.UUID, list[uuid.UUID]] | None
    result_visible: bool
    # See QuizResultDTO - same module-gating reset semantics apply here.
    section_reset: bool = False
    course_reset: bool = False


class QuizGroupContentDTO(BaseDTO):
    max_attempts: int | None = None
    attempts_used: int = 0
    attempts_remaining: int | None = None
    pass_mark_percentage: int | None = None
    show_result_to_student: bool | None = None
    time_limit_seconds: int | None = None
    sections: list[QuizGroupSectionOverviewDTO] = Field(default_factory=list)
    active_attempt: QuizGroupActiveAttemptDTO | None = None
    previous_result: QuizGroupResultDTO | None = None


class QuizGroupSaveProgressDTO(BaseModel):
    attempt_id: uuid.UUID
    answers: dict[uuid.UUID, list[uuid.UUID]]


class QuizGroupSubmitDTO(BaseModel):
    attempt_id: uuid.UUID
    answers: dict[uuid.UUID, list[uuid.UUID]]


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
    is_final_assessment: bool | None = None

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
    # Only meaningful when is_final_assessment - see §4.3/§2.3 in the student docs.
    essay_pass_mark_percentage: int | None = None
    essay_max_attempts: int | None = None
    essay_attempts_used: int | None = None
    essay_attempts_remaining: int | None = None

    # Assessment - quiz group (nested quizzes)
    quiz_group: QuizGroupContentDTO | None = None


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
    # True when this was a *final assessment* and failing it exhausted the
    # student's retries - see the module-gating section of the student docs.
    # `section_reset`: this module was reset (videos/documents/assessments all
    # need redoing). `course_reset`: this was the course's last module, so the
    # *entire* course was reset instead.
    section_reset: bool = False
    course_reset: bool = False


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
