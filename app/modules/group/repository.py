import uuid
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_repository import BaseRepository
from app.common.pagination import PaginationParams
from app.modules.group.entity import Group, GroupMembership
from app.modules.user.entity import User


class GroupRepository(BaseRepository[Group]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Group)

    async def get_by_name(self, name: str) -> Group | None:
        stmt = self._base_select().where(func.lower(Group.name) == name.lower())
        return (await self.session.execute(stmt)).scalar_one_or_none()


class GroupMembershipRepository(BaseRepository[GroupMembership]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, GroupMembership)

    async def get_membership(self, group_id: uuid.UUID, user_id: uuid.UUID) -> GroupMembership | None:
        stmt = self._base_select().where(
            GroupMembership.group_id == group_id, GroupMembership.user_id == user_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_members(
        self, group_id: uuid.UUID, pagination: PaginationParams
    ) -> tuple[Sequence[tuple[GroupMembership, User]], int]:
        stmt = (
            select(GroupMembership, User)
            .join(User, User.id == GroupMembership.user_id)
            .where(GroupMembership.deleted_at.is_(None), GroupMembership.group_id == group_id)
            .order_by(GroupMembership.created_at.desc())
        )
        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        rows = (await self.session.execute(stmt)).all()
        return [(m, u) for m, u in rows], total

    async def list_group_ids_for_user(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        stmt = select(GroupMembership.group_id).where(
            GroupMembership.deleted_at.is_(None), GroupMembership.user_id == user_id
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_active_user_ids_in_group(self, group_id: uuid.UUID) -> list[uuid.UUID]:
        """Every active, non-deleted user currently a member of `group_id`. This is
        the source of truth the Help & Support escalation logic uses to find who to
        notify (e.g. all "Support Desk" members)."""
        stmt = (
            select(User.id)
            .select_from(GroupMembership)
            .join(User, User.id == GroupMembership.user_id)
            .where(
                GroupMembership.deleted_at.is_(None),
                GroupMembership.group_id == group_id,
                User.deleted_at.is_(None),
                User.is_active.is_(True),
            )
        )
        return list((await self.session.execute(stmt)).scalars().all())
