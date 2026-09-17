import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.pagination import PaginatedResponse, PaginationParams
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_admin_user
from app.modules.auth.dto import MessageDTO
from app.modules.instructor_application.dto import (
    ApproveInstructorApplicationRequestDTO,
    InstructorApplicationDetailDTO,
    InstructorApplicationReadDTO,
    RejectInstructorApplicationRequestDTO,
)
from app.modules.instructor_application.entity import InstructorApplicationStatusEnum
from app.modules.instructor_application.service import InstructorApplicationService
from app.modules.user.entity import User

router = APIRouter(
    prefix="/admin/instructor-applications", tags=["Admin - Instructor Applications"], route_class=NoNullAPIRoute
)


@router.get(
    "",
    response_model=PaginatedResponse[InstructorApplicationReadDTO],
    summary="List instructor applications, optionally filtered by status (admin only)",
)
async def list_instructor_applications(
    application_status: InstructorApplicationStatusEnum | None = Query(default=None, alias="status"),
    pagination: PaginationParams = Depends(),
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[InstructorApplicationReadDTO]:
    items, total = await InstructorApplicationService(db).list_applications(pagination, application_status)
    return PaginatedResponse.create(
        items=[InstructorApplicationReadDTO.model_validate(item, from_attributes=True) for item in items],
        total_items=total,
        params=pagination,
    )


@router.get(
    "/{application_id}",
    response_model=ApiResponse[InstructorApplicationDetailDTO],
    summary="Get an instructor application, including a link to download the CV (admin only)",
)
async def get_instructor_application(
    application_id: uuid.UUID,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[InstructorApplicationDetailDTO]:
    result = await InstructorApplicationService(db).get_application_detail(application_id)
    return ApiResponse(message="Instructor application retrieved", data=result)


@router.post(
    "/{application_id}/approve",
    response_model=ApiResponse[InstructorApplicationReadDTO],
    summary="Approve an instructor application and email the applicant a setup link (admin only)",
)
async def approve_instructor_application(
    application_id: uuid.UUID,
    payload: ApproveInstructorApplicationRequestDTO,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[InstructorApplicationReadDTO]:
    application = await InstructorApplicationService(db).approve(application_id, current_admin, payload)
    return ApiResponse(
        message="Application approved. The applicant has been emailed a setup link.",
        data=InstructorApplicationReadDTO.model_validate(application, from_attributes=True),
    )


@router.post(
    "/{application_id}/reject",
    response_model=ApiResponse[InstructorApplicationReadDTO],
    summary="Reject an instructor application and email the applicant (admin only)",
)
async def reject_instructor_application(
    application_id: uuid.UUID,
    payload: RejectInstructorApplicationRequestDTO,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[InstructorApplicationReadDTO]:
    application = await InstructorApplicationService(db).reject(application_id, current_admin, payload)
    return ApiResponse(
        message="Application rejected. The applicant has been notified by email.",
        data=InstructorApplicationReadDTO.model_validate(application, from_attributes=True),
    )


@router.post(
    "/{application_id}/resend-link",
    response_model=ApiResponse[MessageDTO],
    summary="Resend a fresh account-setup link to an approved instructor (admin only)",
)
async def resend_instructor_setup_link(
    application_id: uuid.UUID,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[MessageDTO]:
    await InstructorApplicationService(db).resend_setup_link(application_id, current_admin)
    return ApiResponse(
        message="A fresh setup link has been emailed to the applicant",
        data=MessageDTO(message="Setup link resent"),
    )
