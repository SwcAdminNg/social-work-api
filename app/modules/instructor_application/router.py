from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.auth.dto import LoginResponseDTO
from app.modules.instructor_application.dto import (
    CompleteInstructorSetupRequestDTO,
    InstructorApplicationUploadResponseDTO,
    SubmitInstructorApplicationRequestDTO,
)
from app.modules.instructor_application.service import InstructorApplicationService

router = APIRouter(prefix="/instructor-applications", tags=["Instructor Applications"], route_class=NoNullAPIRoute)


@router.post(
    "",
    response_model=ApiResponse[InstructorApplicationUploadResponseDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Apply to become an instructor and get a presigned URL to upload your CV",
)
async def submit_instructor_application(
    payload: SubmitInstructorApplicationRequestDTO, db: AsyncSession = Depends(get_db)
) -> ApiResponse[InstructorApplicationUploadResponseDTO]:
    result = await InstructorApplicationService(db).submit_application(payload)
    return ApiResponse(
        message="Application submitted. Upload your CV using the provided URL.", data=result
    )


@router.post(
    "/complete-setup",
    response_model=ApiResponse[LoginResponseDTO],
    summary="Complete instructor account setup (username + password) using the emailed setup link",
)
async def complete_instructor_setup(
    payload: CompleteInstructorSetupRequestDTO, db: AsyncSession = Depends(get_db)
) -> ApiResponse[LoginResponseDTO]:
    result = await InstructorApplicationService(db).complete_setup(payload)
    return ApiResponse(message="Account set up. Set up two-factor authentication to continue.", data=result)
