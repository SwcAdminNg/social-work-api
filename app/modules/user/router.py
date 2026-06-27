from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.user.dto import UserReadDTO, UserUpdateDTO
from app.modules.user.entity import User
from app.modules.user.service import UserService

router = APIRouter(prefix="/users", tags=["Users"])


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
