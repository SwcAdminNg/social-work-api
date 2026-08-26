import uuid
from datetime import datetime

from pydantic import Field

from app.common.base_dto import AuditDTO, BaseDTO, CreateDTO, UpdateDTO
from app.modules.course.content_entity import (
    AssessmentTypeEnum,
    EssaySubmissionModeEnum,
    MultiAnswerModeEnum,
    VideoStatusEnum,
)
from app.modules.course.dto import CourseReadDTO, PublicCourseReadDTO
from app.modules.course.entity import CourseItemTypeEnum

# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


class CourseSectionCreateDTO(CreateDTO):
    title: str = Field(min_length=1, max_length=255)
    order_index: int = 0


class CourseSectionUpdateDTO(UpdateDTO):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    order_index: int | None = None


class SectionOrderEntryDTO(BaseDTO):
    id: uuid.UUID
    order_index: int


class CourseSectionReorderDTO(BaseDTO):
    sections: list[SectionOrderEntryDTO]


# ---------------------------------------------------------------------------
# Assessment settings - shared by item creation and the settings-patch endpoint
# ---------------------------------------------------------------------------


class CourseQuizSettingsInDTO(CreateDTO):
    max_attempts: int | None = Field(default=None, ge=1)
    pass_mark_percentage: int = Field(default=70, ge=0, le=100)
    show_result_to_student: bool = True


class CourseQuizSettingsPatchDTO(UpdateDTO):
    max_attempts: int | None = Field(default=None, ge=1)
    pass_mark_percentage: int | None = Field(default=None, ge=0, le=100)
    show_result_to_student: bool | None = None


class CourseEssaySettingsInDTO(CreateDTO):
    question: str = Field(min_length=1)
    description: str = Field(min_length=1)
    submission_mode: EssaySubmissionModeEnum
    # Only meaningfully enforced when this essay is a final assessment (see
    # `is_final_assessment` on CourseItemCreateDTO) - a regular essay has no
    # pass/fail concept and unlimited resubmission regardless of these.
    pass_mark_percentage: int = Field(default=70, ge=0, le=100)
    max_attempts: int | None = Field(default=None, ge=1)


class CourseEssaySettingsPatchDTO(UpdateDTO):
    question: str | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None, min_length=1)
    submission_mode: EssaySubmissionModeEnum | None = None
    pass_mark_percentage: int | None = Field(default=None, ge=0, le=100)
    max_attempts: int | None = Field(default=None, ge=1)


class CourseQuizGroupSettingsInDTO(CreateDTO):
    max_attempts: int | None = Field(default=None, ge=1)
    pass_mark_percentage: int = Field(default=70, ge=0, le=100)
    show_result_to_student: bool = True
    # Null = untimed.
    time_limit_seconds: int | None = Field(default=None, ge=30)


class CourseQuizGroupSettingsPatchDTO(UpdateDTO):
    max_attempts: int | None = Field(default=None, ge=1)
    pass_mark_percentage: int | None = Field(default=None, ge=0, le=100)
    show_result_to_student: bool | None = None
    time_limit_seconds: int | None = Field(default=None, ge=30)


# ---------------------------------------------------------------------------
# Items - create/update payloads
# ---------------------------------------------------------------------------


class CourseItemCreateDTO(CreateDTO):
    title: str = Field(min_length=1, max_length=255)
    item_type: CourseItemTypeEnum
    order_index: int = 0
    is_preview: bool = False
    # Optional estimate of how long a learner takes to get through this item.
    estimated_minutes: int | None = Field(default=None, ge=0)
    # Required only when item_type == DOCUMENT, used to build the R2 storage key.
    file_name: str | None = Field(default=None, max_length=255)
    # Required only when item_type == ASSESSMENT.
    assessment_type: AssessmentTypeEnum | None = None
    due_date: datetime | None = None
    quiz_settings: CourseQuizSettingsInDTO | None = None
    essay_settings: CourseEssaySettingsInDTO | None = None
    # Required only when assessment_type == QUIZ_GROUP. Sections (the nested
    # quizzes) and their question pools are added afterward via their own
    # endpoints, same as standalone quiz questions.
    quiz_group_settings: CourseQuizGroupSettingsInDTO | None = None
    # Marks this assessment as the section's gate: a student must pass it to
    # unlock the next section, and exhausting its retries without passing resets
    # the section (or the whole course, if this is the course's last section) -
    # see the instructor-facing docs for the full flow. At most one per section.
    # If true and the type's own `max_attempts` is left unset, it defaults to 1
    # instead of unlimited - a final assessment needs *some* retry cap for the
    # reset to ever trigger.
    is_final_assessment: bool = False


class CourseAssessmentUpdateDTO(UpdateDTO):
    """Partial update for assessment-level settings. Use `model_dump(exclude_unset=True)`
    so an omitted `due_date` leaves it untouched while an explicit `"due_date": null`
    clears it."""

    due_date: datetime | None = None
    quiz_settings: CourseQuizSettingsPatchDTO | None = None
    essay_settings: CourseEssaySettingsPatchDTO | None = None
    quiz_group_settings: CourseQuizGroupSettingsPatchDTO | None = None
    is_final_assessment: bool | None = None


class CourseItemUpdateDTO(UpdateDTO):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    order_index: int | None = None
    is_preview: bool | None = None
    estimated_minutes: int | None = Field(default=None, ge=0)


class ItemOrderEntryDTO(BaseDTO):
    id: uuid.UUID
    order_index: int


class CourseItemReorderDTO(BaseDTO):
    items: list[ItemOrderEntryDTO]


# ---------------------------------------------------------------------------
# Video
# ---------------------------------------------------------------------------


class CourseVideoPublicDTO(BaseDTO):
    status: VideoStatusEnum
    playback_url: str | None = None
    thumbnail_url: str | None = None
    duration_seconds: int | None = None


class CourseVideoManageDTO(CourseVideoPublicDTO):
    bunny_video_guid: str


class VideoUploadCredentialsDTO(BaseDTO):
    """Everything the frontend needs to start a resumable (TUS) upload directly
    to Bunny Stream - no file bytes ever touch our API."""

    tus_endpoint: str
    library_id: str
    video_id: str
    authorization_signature: str
    authorization_expire: int


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


class CourseDocumentPublicDTO(BaseDTO):
    file_name: str
    mime_type: str | None = None
    file_size_bytes: int | None = None
    is_uploaded: bool


class CourseDocumentManageDTO(CourseDocumentPublicDTO):
    storage_key: str


class DocumentUploadCredentialsDTO(BaseDTO):
    upload_url: str
    storage_key: str


class DocumentFinalizeDTO(BaseDTO):
    mime_type: str | None = None
    file_size_bytes: int | None = Field(default=None, ge=0)


# ---------------------------------------------------------------------------
# Quiz
# ---------------------------------------------------------------------------


class QuizOptionCreateDTO(CreateDTO):
    text: str = Field(min_length=1, max_length=500)
    is_correct: bool = False
    order_index: int = 0


class QuizOptionUpdateDTO(UpdateDTO):
    text: str | None = Field(default=None, min_length=1, max_length=500)
    is_correct: bool | None = None
    order_index: int | None = None


class QuizQuestionCreateDTO(CreateDTO):
    text: str = Field(min_length=1)
    order_index: int = 0
    allow_multiple_answers: bool = False
    # Only meaningful when allow_multiple_answers is True; defaults to OR (partial
    # credit for each correctly ticked option) when left unset. Must be omitted/None
    # for single-answer questions.
    multi_answer_mode: MultiAnswerModeEnum | None = None
    options: list[QuizOptionCreateDTO] = Field(default_factory=list)


class QuizQuestionUpdateDTO(UpdateDTO):
    text: str | None = Field(default=None, min_length=1)
    order_index: int | None = None
    allow_multiple_answers: bool | None = None
    multi_answer_mode: MultiAnswerModeEnum | None = None


class CourseQuizOptionPublicDTO(BaseDTO):
    id: uuid.UUID
    text: str
    order_index: int


class CourseQuizOptionManageDTO(CourseQuizOptionPublicDTO):
    is_correct: bool


class CourseQuizQuestionPublicDTO(BaseDTO):
    id: uuid.UUID
    text: str
    order_index: int
    allow_multiple_answers: bool
    multi_answer_mode: MultiAnswerModeEnum | None
    options: list[CourseQuizOptionPublicDTO]


class CourseQuizQuestionManageDTO(BaseDTO):
    id: uuid.UUID
    text: str
    order_index: int
    allow_multiple_answers: bool
    multi_answer_mode: MultiAnswerModeEnum | None
    options: list[CourseQuizOptionManageDTO]


class QuizAIAutocompleteResponseDTO(BaseDTO):
    source_file_name: str
    source_mime_type: str | None = None
    extracted_text_preview: str
    model: str
    persisted: bool
    generated_questions: list[QuizQuestionCreateDTO]
    created_questions: list[CourseQuizQuestionManageDTO] = Field(default_factory=list)


class CourseQuizDetailDTO(BaseDTO):
    max_attempts: int | None
    pass_mark_percentage: int
    show_result_to_student: bool
    questions: list[CourseQuizQuestionPublicDTO]


class CourseQuizManageDetailDTO(BaseDTO):
    max_attempts: int | None
    pass_mark_percentage: int
    show_result_to_student: bool
    questions: list[CourseQuizQuestionManageDTO]


class CourseEssayDetailDTO(BaseDTO):
    question: str
    description: str
    submission_mode: EssaySubmissionModeEnum
    pass_mark_percentage: int
    max_attempts: int | None


# ---------------------------------------------------------------------------
# Quiz group (nested quizzes) - instructor/admin authoring side
# ---------------------------------------------------------------------------


class QuizGroupSectionCreateDTO(CreateDTO):
    title: str = Field(min_length=1, max_length=255)
    order_index: int = 0
    # How many questions to randomly draw from this section's pool per attempt.
    # Null/omitted = ask every question in the pool every time.
    questions_to_ask: int | None = Field(default=None, ge=1)


class QuizGroupSectionUpdateDTO(UpdateDTO):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    order_index: int | None = None
    questions_to_ask: int | None = Field(default=None, ge=1)


class CourseQuizGroupSectionManageDTO(BaseDTO):
    id: uuid.UUID
    title: str
    order_index: int
    questions_to_ask: int | None
    questions: list[CourseQuizQuestionManageDTO]


class CourseQuizGroupSectionPublicDTO(BaseDTO):
    """Public view deliberately omits the question pool - questions are only
    revealed once a student starts an attempt, so a fixed set can't be studied
    ahead of time and repeat attempts can draw a different subset."""

    id: uuid.UUID
    title: str
    order_index: int
    question_count: int  # how many questions this section will actually ask


class CourseQuizGroupManageDetailDTO(BaseDTO):
    max_attempts: int | None
    pass_mark_percentage: int
    show_result_to_student: bool
    time_limit_seconds: int | None
    sections: list[CourseQuizGroupSectionManageDTO]


class CourseQuizGroupDetailDTO(BaseDTO):
    max_attempts: int | None
    pass_mark_percentage: int
    show_result_to_student: bool
    time_limit_seconds: int | None
    sections: list[CourseQuizGroupSectionPublicDTO]


# ---------------------------------------------------------------------------
# Assessment - the item-level wrapper around quiz/essay/quiz-group settings
# ---------------------------------------------------------------------------


class CourseAssessmentPublicDTO(BaseDTO):
    id: uuid.UUID
    assessment_type: AssessmentTypeEnum
    due_date: datetime | None
    is_final_assessment: bool
    quiz: CourseQuizDetailDTO | None = None
    essay: CourseEssayDetailDTO | None = None
    quiz_group: CourseQuizGroupDetailDTO | None = None


class CourseAssessmentManageDTO(BaseDTO):
    id: uuid.UUID
    assessment_type: AssessmentTypeEnum
    due_date: datetime | None
    is_final_assessment: bool
    quiz: CourseQuizManageDetailDTO | None = None
    essay: CourseEssayDetailDTO | None = None
    quiz_group: CourseQuizGroupManageDetailDTO | None = None


# ---------------------------------------------------------------------------
# Items - read tiers (assembled by the service, not built via from_attributes,
# since video/document/quiz live in separate tables with no ORM relationship)
# ---------------------------------------------------------------------------


class CourseItemReadDTO(AuditDTO):
    section_id: uuid.UUID
    title: str
    item_type: CourseItemTypeEnum
    order_index: int
    is_preview: bool
    estimated_minutes: int | None = None
    video: CourseVideoPublicDTO | None = None
    document: CourseDocumentPublicDTO | None = None
    assessment: CourseAssessmentPublicDTO | None = None


class CourseItemManageReadDTO(AuditDTO):
    section_id: uuid.UUID
    title: str
    item_type: CourseItemTypeEnum
    order_index: int
    is_preview: bool
    estimated_minutes: int | None = None
    video: CourseVideoManageDTO | None = None
    document: CourseDocumentManageDTO | None = None
    assessment: CourseAssessmentManageDTO | None = None


class CourseSectionReadDTO(AuditDTO):
    course_id: uuid.UUID
    title: str
    order_index: int
    items: list[CourseItemReadDTO] = Field(default_factory=list)


class CourseSectionManageReadDTO(AuditDTO):
    course_id: uuid.UUID
    title: str
    order_index: int
    items: list[CourseItemManageReadDTO] = Field(default_factory=list)


class CourseDetailDTO(CourseReadDTO):
    sections: list[CourseSectionReadDTO] = Field(default_factory=list)


from app.modules.course.dto import CourseReadDTO, PublicCourseReadDTO
class CourseManageDetailDTO(CourseReadDTO):
    sections: list[CourseSectionManageReadDTO] = Field(default_factory=list)

class PublicCourseDetailDTO(PublicCourseReadDTO):
    sections: list[CourseSectionReadDTO] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Essay grading (instructor/admin side)
# ---------------------------------------------------------------------------


class EssaySubmissionListItemDTO(BaseDTO):
    user_id: uuid.UUID
    user_full_name: str
    user_email: str
    content_text: str | None
    document_file_name: str | None
    document_download_url: str | None
    submitted_at: datetime
    score: float | None
    is_published: bool
    feedback: str | None


class EssayGradeDTO(CreateDTO):
    score: float = Field(ge=0, le=100)
    feedback: str | None = None
    is_published: bool = False
