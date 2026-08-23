import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.responses import ApiResponse
from app.common.pagination import PaginatedResponse, PaginationParams
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.learning.dto import (
    AssessmentStatsDTO,
    CourseCurriculumDTO,
    EnrolledCourseDTO,
    EssayDocumentFinalizeDTO,
    EssaySubmissionDTO,
    EssaySubmitTextDTO,
    EssayUploadUrlRequestDTO,
    EssayUploadUrlResponseDTO,
    LearningItemContentDTO,
    QuizGroupActiveAttemptDTO,
    QuizGroupResultDTO,
    QuizGroupSaveProgressDTO,
    QuizGroupSubmitDTO,
    QuizResultDTO,
    QuizSubmitDTO,
    UserAssessmentDTO,
)
from app.modules.learning.service import LearningService
from app.modules.user.entity import User

router = APIRouter(prefix="/learning", tags=["Learning"], route_class=NoNullAPIRoute)


@router.post(
    "/courses/{course_id}/enroll",
    response_model=ApiResponse[None],
    summary="Enroll in a course (free or via active subscription)",
)
async def enroll_course(
    course_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    service = LearningService(db)
    result = await service.enroll_course(current_user.id, course_id)
    return ApiResponse(message=result["message"])


@router.get(
    "/courses",
    response_model=PaginatedResponse[EnrolledCourseDTO],
    summary="List enrolled courses with progress",
)
async def list_enrolled_courses(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[EnrolledCourseDTO]:
    service = LearningService(db)
    items, total = await service.list_enrolled_courses(current_user.id, pagination)
    return PaginatedResponse.create(items=items, total_items=total, params=pagination)


@router.get(
    "/courses/{course_id}/curriculum",
    response_model=ApiResponse[CourseCurriculumDTO],
    summary="Get course curriculum with progress tracking",
)
async def get_curriculum(
    course_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CourseCurriculumDTO]:
    service = LearningService(db)
    data = await service.get_curriculum(current_user.id, course_id)
    return ApiResponse(message="Curriculum retrieved successfully", data=data)


@router.get(
    "/courses/{course_id}/items/{item_id}",
    response_model=ApiResponse[LearningItemContentDTO],
    summary="Access specific course item content (video/document/quiz)",
)
async def get_item_content(
    course_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[LearningItemContentDTO]:
    service = LearningService(db)
    data = await service.get_item_content(current_user.id, course_id, item_id)
    return ApiResponse(message="Item content retrieved successfully", data=data)


@router.post(
    "/courses/{course_id}/items/{item_id}/complete",
    response_model=ApiResponse[None],
    summary="Mark a video or document item as completed",
)
async def mark_item_completed(
    course_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    service = LearningService(db)
    await service.mark_item_completed(current_user.id, course_id, item_id)
    return ApiResponse(message="Item marked as completed")


@router.post(
    "/courses/{course_id}/items/{item_id}/quiz/submit",
    response_model=ApiResponse[QuizResultDTO],
    summary="Submit quiz answers and get grading result",
)
async def submit_quiz(
    course_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: QuizSubmitDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[QuizResultDTO]:
    service = LearningService(db)
    data = await service.submit_quiz(current_user.id, course_id, item_id, payload.answers)
    if data.course_reset:
        message = "Quiz failed - out of retries, the entire course has been reset"
    elif data.section_reset:
        message = "Quiz failed - out of retries, this module has been reset"
    elif not data.result_visible:
        message = "Quiz submitted successfully"
    else:
        message = "Quiz passed successfully" if data.passed else "Quiz failed, please try again"
    return ApiResponse(message=message, data=data)


@router.post(
    "/courses/{course_id}/items/{item_id}/quiz-group/start",
    response_model=ApiResponse[QuizGroupActiveAttemptDTO],
    summary="Start (or resume) a quiz group attempt - draws questions per section "
    "(favoring ones not seen before) and starts the timer if one is configured",
)
async def start_quiz_group(
    course_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[QuizGroupActiveAttemptDTO]:
    service = LearningService(db)
    data = await service.start_quiz_group(current_user.id, course_id, item_id)
    return ApiResponse(message="Quiz group attempt started", data=data)


@router.post(
    "/courses/{course_id}/items/{item_id}/quiz-group/progress",
    response_model=ApiResponse[None],
    summary="Autosave in-progress answers for a quiz group attempt (e.g. called "
    "periodically by the client) so a timeout auto-submit has something to score",
)
async def save_quiz_group_progress(
    course_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: QuizGroupSaveProgressDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    service = LearningService(db)
    await service.save_quiz_group_progress(
        current_user.id, course_id, item_id, payload.attempt_id, payload.answers
    )
    return ApiResponse(message="Progress saved")


@router.post(
    "/courses/{course_id}/items/{item_id}/quiz-group/submit",
    response_model=ApiResponse[QuizGroupResultDTO],
    summary="Submit a quiz group attempt (called by the student, or automatically "
    "by the client when the timer runs out) and get the overall grading result",
)
async def submit_quiz_group(
    course_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: QuizGroupSubmitDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[QuizGroupResultDTO]:
    service = LearningService(db)
    data = await service.submit_quiz_group(
        current_user.id, course_id, item_id, payload.attempt_id, payload.answers
    )
    if data.course_reset:
        message = "Quiz group failed - out of retries, the entire course has been reset"
    elif data.section_reset:
        message = "Quiz group failed - out of retries, this module has been reset"
    elif not data.result_visible:
        message = "Quiz group submitted successfully"
    elif data.auto_submitted:
        message = "Time's up - your quiz group was submitted automatically"
    else:
        message = "Quiz group passed successfully" if data.passed else "Quiz group failed, please try again"
    return ApiResponse(message=message, data=data)


@router.post(
    "/courses/{course_id}/items/{item_id}/essay/submit-text",
    response_model=ApiResponse[EssaySubmissionDTO],
    summary="Submit (or resubmit, until graded) a text essay answer",
)
async def submit_essay_text(
    course_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: EssaySubmitTextDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[EssaySubmissionDTO]:
    service = LearningService(db)
    data = await service.submit_essay_text(current_user.id, course_id, item_id, payload.content_text)
    return ApiResponse(message="Essay submitted successfully", data=data)


@router.post(
    "/courses/{course_id}/items/{item_id}/essay/upload-url",
    response_model=ApiResponse[EssayUploadUrlResponseDTO],
    summary="Get a presigned URL to upload a document essay answer directly to R2",
)
async def request_essay_upload_url(
    course_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: EssayUploadUrlRequestDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[EssayUploadUrlResponseDTO]:
    service = LearningService(db)
    data = await service.request_essay_upload_url(current_user.id, course_id, item_id, payload.file_name)
    return ApiResponse(message="Upload URL generated successfully", data=data)


@router.post(
    "/courses/{course_id}/items/{item_id}/essay/submit-document",
    response_model=ApiResponse[EssaySubmissionDTO],
    summary="Confirm a document essay upload to R2 completed (or resubmit, until graded)",
)
async def submit_essay_document(
    course_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: EssayDocumentFinalizeDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[EssaySubmissionDTO]:
    service = LearningService(db)
    data = await service.finalize_essay_document(
        current_user.id, course_id, item_id, payload.storage_key, payload.file_name
    )
    return ApiResponse(message="Essay submitted successfully", data=data)


@router.get(
    "/assessments/me",
    response_model=PaginatedResponse[UserAssessmentDTO],
    summary="List all assessments (quiz or essay) available to the user, with status/score/due date",
)
async def list_my_assessments(
    status: str | None = None,
    course_id: uuid.UUID | None = None,
    assessment_type: str | None = None,
    upcoming: bool = False,
    completed: bool = False,
    retakes: bool = False,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[UserAssessmentDTO]:
    service = LearningService(db)
    items, total = await service.list_user_assessments(
        current_user.id, pagination, status, course_id, assessment_type,
        upcoming, completed, retakes, start_date, end_date,
    )
    return PaginatedResponse.create(items=items, total_items=total, params=pagination)


@router.get(
    "/assessments/stats",
    response_model=ApiResponse[AssessmentStatsDTO],
    summary="Assessment stats for the current user: upcoming, completed, average score, retakes available",
)
async def get_assessment_stats(
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[AssessmentStatsDTO]:
    service = LearningService(db)
    data = await service.get_assessment_stats(current_user.id, start_date, end_date)
    return ApiResponse(message="Assessment stats retrieved successfully", data=data)

