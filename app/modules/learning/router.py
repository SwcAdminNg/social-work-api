import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.responses import ApiResponse
from app.common.pagination import PaginatedResponse, PaginationParams
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.learning.dto import (
    CourseCurriculumDTO,
    EnrolledCourseDTO,
    EssayDocumentFinalizeDTO,
    EssaySubmissionDTO,
    EssaySubmitTextDTO,
    EssayUploadUrlRequestDTO,
    EssayUploadUrlResponseDTO,
    LearningItemContentDTO,
    QuizResultDTO,
    QuizSubmitDTO,
    UserQuizDTO,
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
    if not data.result_visible:
        message = "Quiz submitted successfully"
    else:
        message = "Quiz passed successfully" if data.passed else "Quiz failed, please try again"
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
    "/quizzes/me",
    response_model=PaginatedResponse[UserQuizDTO],
    summary="List all quizzes available to the user with their status",
)
async def list_my_quizzes(
    status: str | None = None,
    course_id: uuid.UUID | None = None,
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[UserQuizDTO]:
    service = LearningService(db)
    items, total = await service.list_user_quizzes(current_user.id, pagination, status, course_id)
    return PaginatedResponse.create(items=items, total_items=total, params=pagination)

