import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.pagination import PaginatedResponse, PaginationParams
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_admin_or_instructor, get_current_user_optional
from app.modules.course.content_dto import DocumentFinalizeDTO, DocumentUploadCredentialsDTO, VideoUploadCredentialsDTO
from app.modules.resource.content_dto import (
    ResourceAttachmentCreateDTO,
    ResourceAttachmentManageReadDTO,
    ResourceAttachmentReorderDTO,
    ResourceAttachmentUpdateDTO,
    ResourceDetailDTO,
    ResourceManageDetailDTO,
)
from app.modules.resource.content_service import ResourceContentService
from app.modules.resource.dto import (
    ResourceCreateDTO,
    ResourceFilterParams,
    ResourceManageFilterParams,
    ResourceReadDTO,
    ResourceThumbnailUploadRequest,
    ResourceThumbnailUploadResponse,
    ResourceUpdateDTO,
)
from app.modules.resource.service import ResourceService
from app.modules.user.entity import User

router = APIRouter(prefix="/resources", tags=["Resources"], route_class=NoNullAPIRoute)


# ---------------------------------------------------------------------------
# Admin/Instructor management - registered before the public `/{slug}` route
# further down, so fixed paths like `/manage` aren't swallowed by it.
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=ApiResponse[ResourceReadDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Create a resource (admin or instructor)",
)
async def create_resource(
    payload: ResourceCreateDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ResourceReadDTO]:
    resource = await ResourceService(db).create(payload, current_user)
    return ApiResponse(message="Resource created successfully", data=ResourceReadDTO.model_validate(resource))


@router.get(
    "/manage",
    response_model=PaginatedResponse[ResourceReadDTO],
    summary="List manageable resources - own for instructors, all for admins",
)
async def list_manage_resources(
    pagination: PaginationParams = Depends(),
    filters: ResourceManageFilterParams = Depends(),
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ResourceReadDTO]:
    items, total = await ResourceService(db).list_manage(pagination, filters, current_user)
    return PaginatedResponse.create(
        items=[ResourceReadDTO.model_validate(item) for item in items], total_items=total, params=pagination
    )


@router.get(
    "/manage/{id}",
    response_model=ApiResponse[ResourceManageDetailDTO],
    summary="Get a resource by id for management, including drafts and unfiltered attachments (admin or owning instructor)",
)
async def get_manage_resource(
    id: uuid.UUID,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ResourceManageDetailDTO]:
    service = ResourceService(db)
    resource = await service.get_for_manage(id, current_user)
    attachments = await ResourceContentService(db).build_attachments(resource.id, manage=True)
    data = ResourceManageDetailDTO(**ResourceReadDTO.model_validate(resource).model_dump(), attachments=attachments)
    return ApiResponse(message="Resource retrieved successfully", data=data)


@router.patch(
    "/{id}",
    response_model=ApiResponse[ResourceReadDTO],
    summary="Update a resource (admin or owning instructor)",
)
async def update_resource(
    id: uuid.UUID,
    payload: ResourceUpdateDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ResourceReadDTO]:
    resource = await ResourceService(db).update(id, payload, current_user)
    return ApiResponse(message="Resource updated successfully", data=ResourceReadDTO.model_validate(resource))


@router.delete(
    "/{id}",
    response_model=ApiResponse[None],
    summary="Delete a resource (admin or owning instructor)",
)
async def delete_resource(
    id: uuid.UUID,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await ResourceService(db).delete(id, current_user)
    return ApiResponse(message="Resource deleted successfully")


@router.patch(
    "/{id}/publish",
    response_model=ApiResponse[ResourceReadDTO],
    summary="Publish or unpublish a resource (admin or owning instructor)",
)
async def set_resource_published(
    id: uuid.UUID,
    is_published: bool,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ResourceReadDTO]:
    resource = await ResourceService(db).set_published(id, is_published, current_user)
    return ApiResponse(message="Resource publish state updated successfully", data=ResourceReadDTO.model_validate(resource))


@router.post(
    "/{id}/thumbnail-upload-url",
    response_model=ApiResponse[ResourceThumbnailUploadResponse],
    summary="Get a pre-signed URL to upload/replace this resource's thumbnail (admin or owning instructor)",
)
async def generate_resource_thumbnail_upload_url(
    id: uuid.UUID,
    payload: ResourceThumbnailUploadRequest,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ResourceThumbnailUploadResponse]:
    data = await ResourceService(db).generate_thumbnail_upload_url(id, payload, current_user)
    return ApiResponse(message="Upload URL generated successfully", data=data)


# ---------------------------------------------------------------------------
# Attachments (video / document / link)
# ---------------------------------------------------------------------------


class AttachmentCreateResponseDTO(ResourceAttachmentManageReadDTO):
    video_upload: VideoUploadCredentialsDTO | None = None
    document_upload: DocumentUploadCredentialsDTO | None = None


@router.post(
    "/{resource_id}/attachments",
    response_model=ApiResponse[AttachmentCreateResponseDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Add an attachment (video/document/link) to a resource (admin or owning instructor)",
)
async def create_attachment(
    resource_id: uuid.UUID,
    payload: ResourceAttachmentCreateDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[AttachmentCreateResponseDTO]:
    attachment, video_credentials, document_credentials = await ResourceContentService(db).create_attachment(
        resource_id, payload, current_user
    )
    data = AttachmentCreateResponseDTO(
        id=attachment.id,
        created_at=attachment.created_at,
        resource_id=attachment.resource_id,
        title=attachment.title,
        attachment_type=attachment.attachment_type,
        order_index=attachment.order_index,
        video_upload=video_credentials,
        document_upload=document_credentials,
    )
    return ApiResponse(message="Attachment created successfully", data=data)


@router.patch(
    "/attachments/{attachment_id}",
    response_model=ApiResponse[None],
    summary="Update an attachment's title/order/downloadable/link fields (admin or owning instructor)",
)
async def update_attachment(
    attachment_id: uuid.UUID,
    payload: ResourceAttachmentUpdateDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await ResourceContentService(db).update_attachment(attachment_id, payload, current_user)
    return ApiResponse(message="Attachment updated successfully")


@router.delete(
    "/attachments/{attachment_id}",
    response_model=ApiResponse[None],
    summary="Delete an attachment (admin or owning instructor)",
)
async def delete_attachment(
    attachment_id: uuid.UUID,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await ResourceContentService(db).delete_attachment(attachment_id, current_user)
    return ApiResponse(message="Attachment deleted successfully")


@router.patch(
    "/{resource_id}/attachments/reorder",
    response_model=ApiResponse[None],
    summary="Reorder a resource's attachments (admin or owning instructor)",
)
async def reorder_attachments(
    resource_id: uuid.UUID,
    payload: ResourceAttachmentReorderDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await ResourceContentService(db).reorder_attachments(resource_id, payload, current_user)
    return ApiResponse(message="Attachments reordered successfully")


@router.post(
    "/attachments/{attachment_id}/document/finalize",
    response_model=ApiResponse[None],
    summary="Confirm a document upload to R2 completed (admin or owning instructor)",
)
async def finalize_attachment_document(
    attachment_id: uuid.UUID,
    payload: DocumentFinalizeDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await ResourceContentService(db).finalize_document(attachment_id, payload, current_user)
    return ApiResponse(message="Document finalized successfully")


@router.post(
    "/attachments/{attachment_id}/video/refresh-upload",
    response_model=ApiResponse[VideoUploadCredentialsDTO],
    summary="Re-issue TUS upload credentials for a video attachment (admin or owning instructor)",
)
async def refresh_attachment_video_upload(
    attachment_id: uuid.UUID,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[VideoUploadCredentialsDTO]:
    credentials = await ResourceContentService(db).refresh_video_upload(attachment_id, current_user)
    return ApiResponse(message="Upload credentials refreshed successfully", data=credentials)


# ---------------------------------------------------------------------------
# Public / optional-auth
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=PaginatedResponse[ResourceReadDTO],
    summary="Browse the public resource library (optional auth)",
)
async def list_resources(
    pagination: PaginationParams = Depends(),
    filters: ResourceFilterParams = Depends(),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ResourceReadDTO]:
    service = ResourceService(db)
    items, total = await service.list_published(pagination, filters)
    data = PaginatedResponse.create(
        items=[ResourceReadDTO.model_validate(item) for item in items], total_items=total, params=pagination
    )
    await service.attach_access(data.data, current_user)
    return data


@router.get(
    "/courses/{course_id}",
    response_model=PaginatedResponse[ResourceReadDTO],
    summary="List published resources tied to a specific course (public, optional auth)",
)
async def list_resources_for_course(
    course_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ResourceReadDTO]:
    service = ResourceService(db)
    filters = ResourceFilterParams(category=None, course_id=course_id, search=None)
    items, total = await service.list_published(pagination, filters)
    data = PaginatedResponse.create(
        items=[ResourceReadDTO.model_validate(item) for item in items], total_items=total, params=pagination
    )
    await service.attach_access(data.data, current_user)
    return data


@router.get(
    "/{slug}",
    response_model=ApiResponse[ResourceDetailDTO],
    summary="Get a published resource by slug (public). Attachments are populated only when "
    "the viewer can access them - see `can_access`/`access_reason`.",
)
async def get_resource_by_slug(
    slug: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ResourceDetailDTO]:
    service = ResourceService(db)
    resource = await service.get_by_slug_published(slug)
    can_access, access_reason = await service.resolve_access(resource, current_user)

    attachments = []
    if can_access:
        attachments = await ResourceContentService(db).build_attachments(resource.id, manage=False)

    base = ResourceReadDTO.model_validate(resource)
    base.can_access = can_access
    base.access_reason = access_reason
    data = ResourceDetailDTO(**base.model_dump(), attachments=attachments)
    return ApiResponse(message="Resource retrieved successfully", data=data)


@router.get(
    "/{slug}/attachments/{attachment_id}/download",
    response_model=ApiResponse[dict],
    summary="Get a fresh, short-lived download URL for a resource document (public)",
)
async def get_resource_document_download_url(
    slug: str,
    attachment_id: uuid.UUID,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    url = await ResourceContentService(db).get_document_download_url(slug, attachment_id, current_user)
    return ApiResponse(message="Download URL generated successfully", data={"download_url": url})
