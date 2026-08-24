import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.pagination import PaginatedResponse, PaginationParams
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_admin_user
from app.modules.group.dto import (
    GroupCreateDTO,
    GroupMemberAddDTO,
    GroupMemberReadDTO,
    GroupReadDTO,
    GroupUpdateDTO,
)
from app.modules.group.service import GroupService
from app.modules.user.entity import User

router = APIRouter(prefix="/groups", tags=["Groups"], route_class=NoNullAPIRoute)


@router.post(
    "",
    response_model=ApiResponse[GroupReadDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Create a group (admin only)",
)
async def create_group(
    payload: GroupCreateDTO,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[GroupReadDTO]:
    group = await GroupService(db).create(payload, current_user)
    return ApiResponse(message="Group created successfully", data=GroupReadDTO.model_validate(group))


@router.get(
    "",
    response_model=PaginatedResponse[GroupReadDTO],
    summary="List all groups (admin only)",
)
async def list_groups(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[GroupReadDTO]:
    items, total = await GroupService(db).list_all(pagination)
    return PaginatedResponse.create(
        items=[GroupReadDTO.model_validate(g) for g in items], total_items=total, params=pagination
    )


@router.get(
    "/users/{user_id}",
    response_model=ApiResponse[list[GroupReadDTO]],
    summary="List the groups a user belongs to (admin only)",
)
async def list_groups_for_user(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[GroupReadDTO]]:
    groups = await GroupService(db).list_groups_for_user(user_id)
    return ApiResponse(message="Groups retrieved successfully", data=groups)


@router.get(
    "/{group_id}",
    response_model=ApiResponse[GroupReadDTO],
    summary="Get a group (admin only)",
)
async def get_group(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[GroupReadDTO]:
    group = await GroupService(db).get(group_id)
    return ApiResponse(message="Group retrieved successfully", data=GroupReadDTO.model_validate(group))


@router.patch(
    "/{group_id}",
    response_model=ApiResponse[GroupReadDTO],
    summary="Update a group (admin only)",
)
async def update_group(
    group_id: uuid.UUID,
    payload: GroupUpdateDTO,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[GroupReadDTO]:
    group = await GroupService(db).update(group_id, payload)
    return ApiResponse(message="Group updated successfully", data=GroupReadDTO.model_validate(group))


@router.post(
    "/{group_id}/deactivate",
    response_model=ApiResponse[GroupReadDTO],
    summary="Deactivate a group (admin only)",
)
async def deactivate_group(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[GroupReadDTO]:
    group = await GroupService(db).deactivate(group_id)
    return ApiResponse(message="Group deactivated successfully", data=GroupReadDTO.model_validate(group))


@router.get(
    "/{group_id}/members",
    response_model=PaginatedResponse[GroupMemberReadDTO],
    summary="List a group's members (admin only)",
)
async def list_group_members(
    group_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[GroupMemberReadDTO]:
    items, total = await GroupService(db).list_members(group_id, pagination)
    return PaginatedResponse.create(items=items, total_items=total, params=pagination)


@router.post(
    "/{group_id}/members",
    response_model=ApiResponse[GroupMemberReadDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Add a user to a group (admin only)",
)
async def add_group_member(
    group_id: uuid.UUID,
    payload: GroupMemberAddDTO,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[GroupMemberReadDTO]:
    member = await GroupService(db).add_member(group_id, payload)
    return ApiResponse(message="Member added successfully", data=member)


@router.delete(
    "/{group_id}/members/{user_id}",
    response_model=ApiResponse[None],
    summary="Remove a user from a group (admin only)",
)
async def remove_group_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await GroupService(db).remove_member(group_id, user_id, current_user)
    return ApiResponse(message="Member removed successfully")
