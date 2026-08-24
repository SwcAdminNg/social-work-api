import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.modules.group.dto import (
    GroupCreateDTO,
    GroupMemberAddDTO,
    GroupMemberReadDTO,
    GroupReadDTO,
    GroupUpdateDTO,
)
from app.modules.group.entity import Group, GroupMembership
from app.modules.group.repository import GroupMembershipRepository, GroupRepository
from app.modules.user.dto import UserReadDTO
from app.modules.user.entity import User
from app.modules.user.repository import UserRepository


class GroupService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = GroupRepository(session)
        self.membership_repo = GroupMembershipRepository(session)
        self.user_repo = UserRepository(session)

    async def create(self, payload: GroupCreateDTO, current_user: User) -> Group:
        if await self.repo.get_by_name(payload.name) is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "A group with this name already exists")
        group = Group(**payload.model_dump())
        await self.repo.create(group)
        await self.session.commit()
        return group

    async def get(self, group_id: uuid.UUID) -> Group:
        group = await self.repo.get_by_id(group_id)
        if group is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
        return group

    async def list_all(self, pagination: PaginationParams) -> tuple[list[Group], int]:
        items, total = await self.repo.list(pagination)
        return list(items), total

    async def update(self, group_id: uuid.UUID, payload: GroupUpdateDTO) -> Group:
        group = await self.get(group_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(group, field, value)
        await self.repo.update(group)
        await self.session.commit()
        return group

    async def deactivate(self, group_id: uuid.UUID) -> Group:
        group = await self.get(group_id)
        group.is_active = False
        await self.repo.update(group)
        await self.session.commit()
        return group

    async def add_member(self, group_id: uuid.UUID, payload: GroupMemberAddDTO) -> GroupMemberReadDTO:
        group = await self.get(group_id)
        user = await self.user_repo.get_by_id(payload.user_id)
        if user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

        existing = await self.membership_repo.get_membership(group.id, user.id)
        if existing is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "User is already a member of this group")

        membership = GroupMembership(group_id=group.id, user_id=user.id)
        await self.membership_repo.create(membership)
        await self.session.commit()
        return GroupMemberReadDTO(
            id=membership.id,
            group_id=membership.group_id,
            user_id=membership.user_id,
            user=UserReadDTO.model_validate(user),
            created_at=membership.created_at,
        )

    async def remove_member(self, group_id: uuid.UUID, user_id: uuid.UUID, current_user: User) -> None:
        membership = await self.membership_repo.get_membership(group_id, user_id)
        if membership is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "This user is not a member of this group")
        await self.membership_repo.soft_delete(membership, current_user.id)
        await self.session.commit()

    async def list_members(
        self, group_id: uuid.UUID, pagination: PaginationParams
    ) -> tuple[list[GroupMemberReadDTO], int]:
        await self.get(group_id)  # 404 if the group itself doesn't exist
        rows, total = await self.membership_repo.list_members(group_id, pagination)
        return [
            GroupMemberReadDTO(
                id=m.id, group_id=m.group_id, user_id=m.user_id, user=UserReadDTO.model_validate(u), created_at=m.created_at
            )
            for m, u in rows
        ], total

    async def list_groups_for_user(self, user_id: uuid.UUID) -> list[GroupReadDTO]:
        group_ids = await self.membership_repo.list_group_ids_for_user(user_id)
        groups = [await self.repo.get_by_id(gid) for gid in group_ids]
        return [GroupReadDTO.model_validate(g) for g in groups if g is not None]
