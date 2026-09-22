import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.pagination import PaginatedResponse, PaginationParams
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_admin_user, get_current_instructor_user, get_current_user
from app.modules.user.dto import (
    CvDownloadResponseDTO,
    CvUploadRequestDTO,
    CvUploadResponseDTO,
    InstructorDocumentReadDTO,
    InstructorDocumentUpdateDTO,
    InstructorDocumentUploadRequestDTO,
    InstructorDocumentUploadResponseDTO,
    ProfilePictureUploadRequest,
    ProfilePictureUploadResponse,
    UserFilterParams,
    UserReadDTO,
    UserRoleUpdateDTO,
    UserUpdateDTO,
)
from app.modules.user.entity import User
from app.modules.user.service import UserService

router = APIRouter(prefix="/users", tags=["Users"], route_class=NoNullAPIRoute)


@router.get("", response_model=PaginatedResponse[UserReadDTO], summary="List all users (admin only)")
async def list_users(
    pagination: PaginationParams = Depends(),
    filters: UserFilterParams = Depends(),
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[UserReadDTO]:
    items, total = await UserService(db).list(pagination, filters)
    return PaginatedResponse.create(
        items=[UserReadDTO.model_validate(item) for item in items],
        total_items=total,
        params=pagination,
    )


@router.get("/me", response_model=ApiResponse[UserReadDTO], summary="Get the current authenticated user's profile")
async def get_my_profile(current_user: User = Depends(get_current_user)) -> ApiResponse[UserReadDTO]:
    return ApiResponse(message="Profile retrieved successfully", data=UserReadDTO.model_validate(current_user))


@router.patch("/me", response_model=ApiResponse[UserReadDTO], summary="Update the current authenticated user's profile")
async def update_my_profile(
    payload: UserUpdateDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[UserReadDTO]:
    updated_user = await UserService(db).update_profile(current_user, payload)
    return ApiResponse(message="Profile updated successfully", data=UserReadDTO.model_validate(updated_user))


@router.post(
    "/me/profile-picture-upload-url",
    response_model=ApiResponse[ProfilePictureUploadResponse],
    summary="Get a pre-signed URL to upload the current user's profile picture",
)
async def get_profile_picture_upload_url(
    payload: ProfilePictureUploadRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ProfilePictureUploadResponse]:
    data = await UserService(db).generate_profile_picture_upload_url(current_user, payload)
    return ApiResponse(message="Upload URL generated successfully", data=data)


@router.post(
    "/me/cv-upload-url",
    response_model=ApiResponse[CvUploadResponseDTO],
    summary="Get a pre-signed URL to upload/replace the current instructor's CV",
)
async def get_cv_upload_url(
    payload: CvUploadRequestDTO,
    current_user: User = Depends(get_current_instructor_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CvUploadResponseDTO]:
    data = await UserService(db).generate_cv_upload_url(current_user, payload)
    return ApiResponse(message="Upload URL generated successfully", data=data)


@router.get(
    "/me/cv-download-url",
    response_model=ApiResponse[CvDownloadResponseDTO],
    summary="Get a pre-signed URL to download the current instructor's CV",
)
async def get_cv_download_url(
    current_user: User = Depends(get_current_instructor_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CvDownloadResponseDTO]:
    data = await UserService(db).get_cv_download_url(current_user)
    return ApiResponse(message="Download URL generated successfully", data=data)


@router.get(
    "/me/documents",
    response_model=ApiResponse[list[InstructorDocumentReadDTO]],
    summary="List the current instructor's additional profile documents (e.g. License, Certification)",
)
async def list_my_documents(
    current_user: User = Depends(get_current_instructor_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[InstructorDocumentReadDTO]]:
    data = await UserService(db).list_documents(current_user)
    return ApiResponse(message="Documents retrieved successfully", data=data)


@router.post(
    "/me/documents",
    response_model=ApiResponse[InstructorDocumentUploadResponseDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Add a new named document to the current instructor's profile and get a pre-signed upload URL for it",
)
async def create_my_document(
    payload: InstructorDocumentUploadRequestDTO,
    current_user: User = Depends(get_current_instructor_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[InstructorDocumentUploadResponseDTO]:
    data = await UserService(db).create_document_upload_url(current_user, payload)
    return ApiResponse(message="Upload URL generated successfully", data=data)


@router.patch(
    "/me/documents/{document_id}",
    response_model=ApiResponse[InstructorDocumentReadDTO],
    summary="Rename one of the current instructor's documents",
)
async def update_my_document(
    document_id: uuid.UUID,
    payload: InstructorDocumentUpdateDTO,
    current_user: User = Depends(get_current_instructor_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[InstructorDocumentReadDTO]:
    data = await UserService(db).update_document(current_user, document_id, payload)
    return ApiResponse(message="Document updated successfully", data=data)


@router.post(
    "/me/documents/{document_id}/upload-url",
    response_model=ApiResponse[InstructorDocumentUploadResponseDTO],
    summary="Replace an existing document's file (and optionally its name), getting a new pre-signed upload URL",
)
async def replace_my_document_file(
    document_id: uuid.UUID,
    payload: InstructorDocumentUploadRequestDTO,
    current_user: User = Depends(get_current_instructor_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[InstructorDocumentUploadResponseDTO]:
    data = await UserService(db).replace_document_file(current_user, document_id, payload)
    return ApiResponse(message="Upload URL generated successfully", data=data)


@router.delete(
    "/me/documents/{document_id}",
    response_model=ApiResponse[None],
    summary="Delete one of the current instructor's documents",
)
async def delete_my_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_instructor_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await UserService(db).delete_document(current_user, document_id)
    return ApiResponse(message="Document deleted successfully")


@router.get("/{user_id}", response_model=ApiResponse[UserReadDTO], summary="Get user details by ID (admin only)")
async def get_user(
    user_id: str,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[UserReadDTO]:
    service = UserService(db)
    user = await service.get_by_id(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
        
    return ApiResponse(message="User details retrieved successfully", data=UserReadDTO.model_validate(user))


@router.post("/{user_id}/suspend", response_model=ApiResponse[UserReadDTO], summary="Suspend a user (admin only)")
async def suspend_user(
    user_id: str,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[UserReadDTO]:
    if str(current_admin.id) == str(user_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot suspend yourself")
    
    service = UserService(db)
    user = await service.get_by_id(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
        
    updated_user = await service.set_suspend_status(user, True)
    return ApiResponse(message="User suspended successfully", data=UserReadDTO.model_validate(updated_user))


@router.post("/{user_id}/unsuspend", response_model=ApiResponse[UserReadDTO], summary="Unsuspend a user (admin only)")
async def unsuspend_user(
    user_id: str,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[UserReadDTO]:
    service = UserService(db)
    user = await service.get_by_id(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
        
    updated_user = await service.set_suspend_status(user, False)
    return ApiResponse(message="User unsuspended successfully", data=UserReadDTO.model_validate(updated_user))


@router.patch("/{user_id}/role", response_model=ApiResponse[UserReadDTO], summary="Change user role (admin only)")
async def change_user_role(
    user_id: str,
    payload: UserRoleUpdateDTO,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[UserReadDTO]:
    if str(current_admin.id) == str(user_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot change your own role")
        
    service = UserService(db)
    user = await service.get_by_id(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
        
    updated_user = await service.update_role(user, payload.role)
    return ApiResponse(message="User role updated successfully", data=UserReadDTO.model_validate(updated_user))
