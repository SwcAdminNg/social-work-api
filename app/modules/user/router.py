from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.pagination import PaginatedResponse, PaginationParams
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_admin_user, get_current_user
from app.modules.user.dto import UserFilterParams, UserReadDTO, UserRoleUpdateDTO, UserUpdateDTO
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
