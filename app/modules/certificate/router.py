import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.pagination import PaginatedResponse, PaginationParams
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.core.qstash import verify_qstash_signature
from app.modules.auth.dependencies import get_current_admin_or_instructor, get_current_user
from app.modules.certificate.dto import (
    CertificateImageUploadRequestDTO,
    CertificateImageUploadResponseDTO,
    CertificateReadDTO,
    CertificateTemplateCreateDTO,
    CertificateTemplateReadDTO,
    CertificateTemplateUpdateDTO,
    CourseCertificateSettingsUpdateDTO,
    PublicCertificateVerifyDTO,
)
from app.modules.certificate.service import CertificateService, CertificateTemplateService
from app.modules.user.entity import User

router = APIRouter(prefix="/certificates", tags=["Certificates"], route_class=NoNullAPIRoute)


# ---------------------------------------------------------------------------
# Templates (admin or instructor)
# ---------------------------------------------------------------------------


@router.post(
    "/templates",
    response_model=ApiResponse[CertificateTemplateReadDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Create a certificate template (admin creates global templates; instructors create their own)",
)
async def create_certificate_template(
    payload: CertificateTemplateCreateDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CertificateTemplateReadDTO]:
    template = await CertificateTemplateService(db).create(payload, current_user)
    return ApiResponse(
        message="Certificate template created successfully", data=CertificateTemplateReadDTO.from_entity(template)
    )


@router.get(
    "/templates",
    response_model=PaginatedResponse[CertificateTemplateReadDTO],
    summary="List certificate templates available to the current admin/instructor (own + global)",
)
async def list_certificate_templates(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[CertificateTemplateReadDTO]:
    items, total = await CertificateTemplateService(db).list_available(pagination, current_user)
    return PaginatedResponse.create(
        items=[CertificateTemplateReadDTO.from_entity(t) for t in items], total_items=total, params=pagination
    )


@router.get(
    "/templates/{template_id}",
    response_model=ApiResponse[CertificateTemplateReadDTO],
    summary="Get a certificate template (admin or owning instructor)",
)
async def get_certificate_template(
    template_id: uuid.UUID,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CertificateTemplateReadDTO]:
    template = await CertificateTemplateService(db).get_for_manage(template_id, current_user)
    return ApiResponse(
        message="Certificate template retrieved successfully", data=CertificateTemplateReadDTO.from_entity(template)
    )


@router.patch(
    "/templates/{template_id}",
    response_model=ApiResponse[CertificateTemplateReadDTO],
    summary="Update a certificate template's design (admin or owning instructor)",
)
async def update_certificate_template(
    template_id: uuid.UUID,
    payload: CertificateTemplateUpdateDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CertificateTemplateReadDTO]:
    template = await CertificateTemplateService(db).update(template_id, payload, current_user)
    return ApiResponse(
        message="Certificate template updated successfully", data=CertificateTemplateReadDTO.from_entity(template)
    )


@router.delete(
    "/templates/{template_id}",
    response_model=ApiResponse[None],
    summary="Delete a certificate template (admin or owning instructor)",
)
async def delete_certificate_template(
    template_id: uuid.UUID,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await CertificateTemplateService(db).delete(template_id, current_user)
    return ApiResponse(message="Certificate template deleted successfully")


@router.post(
    "/templates/{template_id}/logo-upload-url",
    response_model=ApiResponse[CertificateImageUploadResponseDTO],
    summary="Get a pre-signed URL to upload/replace this template's logo (admin or owning instructor)",
)
async def get_certificate_template_logo_upload_url(
    template_id: uuid.UUID,
    payload: CertificateImageUploadRequestDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CertificateImageUploadResponseDTO]:
    data = await CertificateTemplateService(db).generate_image_upload_url(template_id, "logo", payload, current_user)
    return ApiResponse(message="Logo upload URL generated successfully", data=data)


@router.post(
    "/templates/{template_id}/signature-upload-url",
    response_model=ApiResponse[CertificateImageUploadResponseDTO],
    summary="Get a pre-signed URL to upload/replace this template's signature image (admin or owning instructor)",
)
async def get_certificate_template_signature_upload_url(
    template_id: uuid.UUID,
    payload: CertificateImageUploadRequestDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CertificateImageUploadResponseDTO]:
    data = await CertificateTemplateService(db).generate_image_upload_url(
        template_id, "signature", payload, current_user
    )
    return ApiResponse(message="Signature upload URL generated successfully", data=data)


# ---------------------------------------------------------------------------
# Course <-> template assignment (admin or owning instructor)
# ---------------------------------------------------------------------------


@router.patch(
    "/courses/{course_id}/settings",
    response_model=ApiResponse[None],
    summary="Enable/disable certificates for a course and/or set its certificate template "
    "(admin or owning instructor)",
)
async def update_course_certificate_settings(
    course_id: uuid.UUID,
    payload: CourseCertificateSettingsUpdateDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await CertificateService(db).update_course_certificate_settings(course_id, payload, current_user)
    return ApiResponse(message="Course certificate settings updated successfully")


# ---------------------------------------------------------------------------
# Student-facing
# ---------------------------------------------------------------------------


@router.get(
    "/mine",
    response_model=PaginatedResponse[CertificateReadDTO],
    summary="List certificates earned by the current user",
)
async def list_my_certificates(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[CertificateReadDTO]:
    items, total = await CertificateService(db).list_my_certificates(current_user, pagination)
    return PaginatedResponse.create(items=items, total_items=total, params=pagination)


@router.get(
    "/mine/{course_id}",
    response_model=ApiResponse[CertificateReadDTO],
    summary="Get (and lazily render) the current user's certificate for a completed course",
)
async def get_my_certificate(
    course_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CertificateReadDTO]:
    data = await CertificateService(db).get_my_certificate(current_user, course_id)
    return ApiResponse(message="Certificate retrieved successfully", data=data)


# ---------------------------------------------------------------------------
# Public verification
# ---------------------------------------------------------------------------


@router.get(
    "/verify/{verification_code}",
    response_model=ApiResponse[PublicCertificateVerifyDTO],
    summary="Publicly verify a certificate by its verification code (no auth required)",
)
async def verify_certificate(
    verification_code: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PublicCertificateVerifyDTO]:
    data = await CertificateService(db).verify(verification_code)
    message = "Certificate is valid" if data.valid else "Certificate could not be verified"
    return ApiResponse(message=message, data=data)


# ---------------------------------------------------------------------------
# Cron (QStash)
# ---------------------------------------------------------------------------


@router.post(
    "/cron/process-scheduled-certificates",
    summary="Cron endpoint that issues certificates for SCHEDULED courses whose "
    "access_end_date has passed (via QStash)",
    include_in_schema=False,
)
async def process_scheduled_certificates_cron(
    raw_body: bytes = Depends(verify_qstash_signature),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await CertificateService(db).process_scheduled_course_certificates()
    return {"status": "ok", "data": result}
