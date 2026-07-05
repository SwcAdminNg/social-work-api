import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.pagination import PaginatedResponse, PaginationParams
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_admin_or_instructor
from app.modules.course.content_dto import (
    CourseDetailDTO,
    CourseItemCreateDTO,
    CourseItemManageReadDTO,
    CourseItemReorderDTO,
    CourseItemUpdateDTO,
    CourseManageDetailDTO,
    CourseQuizOptionManageDTO,
    CourseQuizQuestionManageDTO,
    CourseSectionCreateDTO,
    CourseSectionManageReadDTO,
    CourseSectionReorderDTO,
    CourseSectionUpdateDTO,
    DocumentFinalizeDTO,
    DocumentUploadCredentialsDTO,
    QuizOptionCreateDTO,
    QuizOptionUpdateDTO,
    QuizQuestionCreateDTO,
    QuizQuestionUpdateDTO,
    VideoUploadCredentialsDTO,
)
from app.modules.course.content_service import CourseContentService
from app.modules.course.dto import (
    CourseCreateDTO,
    CourseFilterParams,
    CourseManageFilterParams,
    CourseReadDTO,
    CourseThumbnailUploadRequest,
    CourseThumbnailUploadResponse,
    CourseUpdateDTO,
)
from app.modules.course.service import CourseService
from app.modules.user.entity import User

router = APIRouter(prefix="/courses", tags=["Courses"], route_class=NoNullAPIRoute)


# ---------------------------------------------------------------------------
# Course CRUD
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=ApiResponse[CourseReadDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Create a draft course (admin or instructor)",
)
async def create_course(
    payload: CourseCreateDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CourseReadDTO]:
    course = await CourseService(db).create(payload, current_user)
    return ApiResponse(message="Course created successfully", data=CourseReadDTO.model_validate(course))


@router.post(
    "/manage/{course_id}/thumbnail-upload-url",
    response_model=ApiResponse[CourseThumbnailUploadResponse],
    summary="Get a pre-signed URL to upload a course thumbnail (admin or owning instructor)",
)
async def get_thumbnail_upload_url(
    course_id: uuid.UUID,
    payload: CourseThumbnailUploadRequest,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CourseThumbnailUploadResponse]:
    data = await CourseService(db).generate_thumbnail_upload_url(course_id, payload, current_user)
    return ApiResponse(message="Thumbnail upload URL generated successfully", data=data)


@router.get(
    "",
    response_model=PaginatedResponse[CourseReadDTO],
    summary="List published courses (public)",
)
async def list_courses(
    pagination: PaginationParams = Depends(),
    filters: CourseFilterParams = Depends(),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[CourseReadDTO]:
    items, total = await CourseService(db).list_published(pagination, filters)
    return PaginatedResponse.create(
        items=[CourseReadDTO.model_validate(item) for item in items], total_items=total, params=pagination
    )


@router.get(
    "/enrolled",
    response_model=PaginatedResponse[CourseReadDTO],
    summary="List courses the current user is enrolled in",
)
async def list_enrolled_courses(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[CourseReadDTO]:
    items, total = await CourseService(db).list_enrolled(current_user, pagination)
    return PaginatedResponse.create(
        items=[CourseReadDTO.model_validate(item) for item in items], total_items=total, params=pagination
    )


@router.get(
    "/manage",
    response_model=PaginatedResponse[CourseReadDTO],
    summary="List manageable courses - own courses for instructors, all for admins",
)
async def list_manage_courses(
    pagination: PaginationParams = Depends(),
    filters: CourseManageFilterParams = Depends(),
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[CourseReadDTO]:
    items, total = await CourseService(db).list_manage(pagination, filters, current_user)
    return PaginatedResponse.create(
        items=[CourseReadDTO.model_validate(item) for item in items], total_items=total, params=pagination
    )


@router.get(
    "/manage/{id}",
    response_model=ApiResponse[CourseManageDetailDTO],
    summary="Get a course by id for management, including drafts (admin or owning instructor)",
)
async def get_manage_course(
    id: uuid.UUID,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CourseManageDetailDTO]:
    course = await CourseService(db).get_for_manage(id, current_user)
    sections = await CourseContentService(db).build_tree(course.id, manage=True)
    data = CourseManageDetailDTO(**CourseReadDTO.model_validate(course).model_dump(), sections=sections)
    return ApiResponse(message="Course retrieved successfully", data=data)


@router.get(
    "/{slug}",
    response_model=ApiResponse[CourseDetailDTO],
    summary="Get a published course by slug (public)",
)
async def get_course_by_slug(slug: str, db: AsyncSession = Depends(get_db)) -> ApiResponse[CourseDetailDTO]:
    course = await CourseService(db).get_by_slug_published(slug)
    sections = await CourseContentService(db).build_tree(course.id, manage=False)
    data = CourseDetailDTO(**CourseReadDTO.model_validate(course).model_dump(), sections=sections)
    return ApiResponse(message="Course retrieved successfully", data=data)


@router.patch(
    "/{id}",
    response_model=ApiResponse[CourseReadDTO],
    summary="Update a course (admin or owning instructor)",
)
async def update_course(
    id: uuid.UUID,
    payload: CourseUpdateDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CourseReadDTO]:
    course = await CourseService(db).update(id, payload, current_user)
    return ApiResponse(message="Course updated successfully", data=CourseReadDTO.model_validate(course))


@router.patch(
    "/{id}/publish",
    response_model=ApiResponse[CourseReadDTO],
    summary="Publish or unpublish a course (admin or owning instructor)",
)
async def set_course_published(
    id: uuid.UUID,
    is_published: bool,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CourseReadDTO]:
    course = await CourseService(db).set_published(id, is_published, current_user)
    message = "Course published successfully" if is_published else "Course unpublished successfully"
    return ApiResponse(message=message, data=CourseReadDTO.model_validate(course))


@router.delete(
    "/{id}",
    response_model=ApiResponse[None],
    summary="Delete a course (admin or owning instructor)",
)
async def delete_course(
    id: uuid.UUID,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await CourseService(db).delete(id, current_user)
    return ApiResponse(message="Course deleted successfully")


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


@router.post(
    "/{course_id}/sections",
    response_model=ApiResponse[CourseSectionManageReadDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Add a curriculum section to a course (admin or owning instructor)",
)
async def create_section(
    course_id: uuid.UUID,
    payload: CourseSectionCreateDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CourseSectionManageReadDTO]:
    section = await CourseContentService(db).create_section(course_id, payload, current_user)
    return ApiResponse(
        message="Section created successfully",
        data=CourseSectionManageReadDTO(
            id=section.id, created_at=section.created_at, course_id=section.course_id,
            title=section.title, order_index=section.order_index, items=[],
        ),
    )


@router.patch(
    "/{course_id}/sections/reorder",
    response_model=ApiResponse[None],
    summary="Reorder sections within a course (admin or owning instructor)",
)
async def reorder_sections(
    course_id: uuid.UUID,
    payload: CourseSectionReorderDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await CourseContentService(db).reorder_sections(course_id, payload, current_user)
    return ApiResponse(message="Sections reordered successfully")


@router.patch(
    "/{course_id}/sections/{section_id}",
    response_model=ApiResponse[CourseSectionManageReadDTO],
    summary="Update a section (admin or owning instructor)",
)
async def update_section(
    course_id: uuid.UUID,
    section_id: uuid.UUID,
    payload: CourseSectionUpdateDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CourseSectionManageReadDTO]:
    section = await CourseContentService(db).update_section(course_id, section_id, payload, current_user)
    return ApiResponse(
        message="Section updated successfully",
        data=CourseSectionManageReadDTO(
            id=section.id, created_at=section.created_at, course_id=section.course_id,
            title=section.title, order_index=section.order_index, items=[],
        ),
    )


@router.delete(
    "/{course_id}/sections/{section_id}",
    response_model=ApiResponse[None],
    summary="Delete a section (admin or owning instructor)",
)
async def delete_section(
    course_id: uuid.UUID,
    section_id: uuid.UUID,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await CourseContentService(db).delete_section(course_id, section_id, current_user)
    return ApiResponse(message="Section deleted successfully")


# ---------------------------------------------------------------------------
# Items (quiz / document / video)
# ---------------------------------------------------------------------------


class ItemCreateResponseDTO(CourseItemManageReadDTO):
    video_upload: VideoUploadCredentialsDTO | None = None
    document_upload: DocumentUploadCredentialsDTO | None = None


@router.post(
    "/{course_id}/sections/{section_id}/items",
    response_model=ApiResponse[ItemCreateResponseDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Add a curriculum item (quiz/document/video) to a section. For VIDEO/DOCUMENT "
    "types the response includes the upload credentials the frontend uses to upload "
    "directly to Bunny Stream / Cloudflare R2.",
)
async def create_item(
    course_id: uuid.UUID,
    section_id: uuid.UUID,
    payload: CourseItemCreateDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ItemCreateResponseDTO]:
    item, video_credentials, document_credentials = await CourseContentService(db).create_item(
        course_id, section_id, payload, current_user
    )
    data = ItemCreateResponseDTO(
        id=item.id,
        created_at=item.created_at,
        section_id=item.section_id,
        title=item.title,
        item_type=item.item_type,
        order_index=item.order_index,
        is_preview=item.is_preview,
        video_upload=video_credentials,
        document_upload=document_credentials,
    )
    return ApiResponse(message="Item created successfully", data=data)


@router.patch(
    "/items/{item_id}",
    response_model=ApiResponse[None],
    summary="Update a curriculum item's title/order/preview flag (admin or owning instructor)",
)
async def update_item(
    item_id: uuid.UUID,
    payload: CourseItemUpdateDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await CourseContentService(db).update_item(item_id, payload, current_user)
    return ApiResponse(message="Item updated successfully")


@router.delete(
    "/items/{item_id}",
    response_model=ApiResponse[None],
    summary="Delete a curriculum item (admin or owning instructor)",
)
async def delete_item(
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await CourseContentService(db).delete_item(item_id, current_user)
    return ApiResponse(message="Item deleted successfully")


@router.patch(
    "/{course_id}/sections/{section_id}/items/reorder",
    response_model=ApiResponse[None],
    summary="Reorder items within a section (admin or owning instructor)",
)
async def reorder_items(
    course_id: uuid.UUID,
    section_id: uuid.UUID,
    payload: CourseItemReorderDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await CourseContentService(db).reorder_items(course_id, section_id, payload, current_user)
    return ApiResponse(message="Items reordered successfully")


# ---------------------------------------------------------------------------
# Document content
# ---------------------------------------------------------------------------


@router.post(
    "/items/{item_id}/document/finalize",
    response_model=ApiResponse[None],
    summary="Confirm a document upload to R2 completed (admin or owning instructor)",
)
async def finalize_document(
    item_id: uuid.UUID,
    payload: DocumentFinalizeDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await CourseContentService(db).finalize_document(item_id, payload, current_user)
    return ApiResponse(message="Document finalized successfully")


@router.get(
    "/{slug}/items/{item_id}/download",
    response_model=ApiResponse[dict],
    summary="Get a fresh, short-lived download URL for a course document (public)",
)
async def get_document_download_url(
    slug: str, item_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> ApiResponse[dict]:
    url = await CourseContentService(db).get_document_download_url(slug, item_id)
    return ApiResponse(message="Download URL generated successfully", data={"download_url": url})


# ---------------------------------------------------------------------------
# Video content
# ---------------------------------------------------------------------------


@router.post(
    "/items/{item_id}/video/refresh-upload",
    response_model=ApiResponse[VideoUploadCredentialsDTO],
    summary="Re-issue TUS upload credentials for a video item (admin or owning instructor)",
)
async def refresh_video_upload(
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[VideoUploadCredentialsDTO]:
    credentials = await CourseContentService(db).refresh_video_upload(item_id, current_user)
    return ApiResponse(message="Upload credentials refreshed successfully", data=credentials)


# ---------------------------------------------------------------------------
# Quiz content
# ---------------------------------------------------------------------------


@router.post(
    "/items/{item_id}/quiz/questions",
    response_model=ApiResponse[CourseQuizQuestionManageDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Add a question (with options) to a quiz item (admin or owning instructor)",
)
async def create_quiz_question(
    item_id: uuid.UUID,
    payload: QuizQuestionCreateDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CourseQuizQuestionManageDTO]:
    question, created_options = await CourseContentService(db).create_question(item_id, payload, current_user)
    options = [
        CourseQuizOptionManageDTO(id=o.id, text=o.text, order_index=o.order_index, is_correct=o.is_correct)
        for o in created_options
    ]
    data = CourseQuizQuestionManageDTO(
        id=question.id, text=question.text, order_index=question.order_index,
        allow_multiple_answers=question.allow_multiple_answers, options=options,
    )
    return ApiResponse(message="Question created successfully", data=data)


@router.patch(
    "/quiz/questions/{question_id}",
    response_model=ApiResponse[None],
    summary="Update a quiz question (admin or owning instructor)",
)
async def update_quiz_question(
    question_id: uuid.UUID,
    payload: QuizQuestionUpdateDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await CourseContentService(db).update_question(question_id, payload, current_user)
    return ApiResponse(message="Question updated successfully")


@router.delete(
    "/quiz/questions/{question_id}",
    response_model=ApiResponse[None],
    summary="Delete a quiz question (admin or owning instructor)",
)
async def delete_quiz_question(
    question_id: uuid.UUID,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await CourseContentService(db).delete_question(question_id, current_user)
    return ApiResponse(message="Question deleted successfully")


@router.post(
    "/quiz/questions/{question_id}/options",
    response_model=ApiResponse[CourseQuizOptionManageDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Add an option to a quiz question (admin or owning instructor)",
)
async def create_quiz_option(
    question_id: uuid.UUID,
    payload: QuizOptionCreateDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CourseQuizOptionManageDTO]:
    option = await CourseContentService(db).create_option(question_id, payload, current_user)
    data = CourseQuizOptionManageDTO(
        id=option.id, text=option.text, order_index=option.order_index, is_correct=option.is_correct
    )
    return ApiResponse(message="Option created successfully", data=data)


@router.patch(
    "/quiz/options/{option_id}",
    response_model=ApiResponse[None],
    summary="Update a quiz option (admin or owning instructor)",
)
async def update_quiz_option(
    option_id: uuid.UUID,
    payload: QuizOptionUpdateDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await CourseContentService(db).update_option(option_id, payload, current_user)
    return ApiResponse(message="Option updated successfully")


@router.delete(
    "/quiz/options/{option_id}",
    response_model=ApiResponse[None],
    summary="Delete a quiz option (admin or owning instructor)",
)
async def delete_quiz_option(
    option_id: uuid.UUID,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await CourseContentService(db).delete_option(option_id, current_user)
    return ApiResponse(message="Option deleted successfully")
