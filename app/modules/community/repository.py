import uuid
from datetime import datetime
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_repository import BaseRepository
from app.common.pagination import PaginationParams
from app.modules.community.entity import (
    Community,
    CommunityMembership,
    CommunityMembershipAddedViaEnum,
    CommunityRead,
    CommunityTypeEnum,
)


class CommunityRepository(BaseRepository[Community]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Community)

    async def get_by_course_id(self, course_id: uuid.UUID) -> Community | None:
        stmt = self._base_select().where(
            Community.type == CommunityTypeEnum.COURSE, Community.course_id == course_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_singleton(self, community_type: CommunityTypeEnum) -> Community | None:
        stmt = self._base_select().where(Community.type == community_type)
        return (await self.session.execute(stmt)).scalars().first()

    async def list_by_type(self, community_type: CommunityTypeEnum) -> Sequence[Community]:
        stmt = self._base_select().where(Community.type == community_type)
        return (await self.session.execute(stmt)).scalars().all()

    async def list_for_courses(self, course_ids: Sequence[uuid.UUID]) -> Sequence[Community]:
        if not course_ids:
            return []
        stmt = self._base_select().where(
            Community.type == CommunityTypeEnum.COURSE, Community.course_id.in_(course_ids)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def list_custom(
        self, pagination: PaginationParams, search: str | None = None
    ) -> tuple[Sequence[Community], int]:
        stmt = self._base_select().where(Community.type == CommunityTypeEnum.CUSTOM)
        if search:
            stmt = stmt.where(Community.name.ilike(f"%{search}%"))
        stmt = stmt.order_by(Community.created_at.desc())

        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total


class CommunityMembershipRepository(BaseRepository[CommunityMembership]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CommunityMembership)

    async def get_membership(self, community_id: uuid.UUID, user_id: uuid.UUID) -> CommunityMembership | None:
        stmt = self._base_select().where(
            CommunityMembership.community_id == community_id, CommunityMembership.user_id == user_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add_members(
        self,
        community_id: uuid.UUID,
        user_ids: Sequence[uuid.UUID],
        added_via: CommunityMembershipAddedViaEnum,
        added_from_course_id: uuid.UUID | None = None,
    ) -> None:
        """Pre-filters already-member user ids, then inserts only the diff - avoids
        a Postgres-specific upsert, consistent with how the rest of the codebase
        does plain SQLAlchemy 2.0 without dialect-specific insert syntax."""
        if not user_ids:
            return
        existing_stmt = select(CommunityMembership.user_id).where(
            CommunityMembership.deleted_at.is_(None),
            CommunityMembership.community_id == community_id,
            CommunityMembership.user_id.in_(user_ids),
        )
        existing_ids = set((await self.session.execute(existing_stmt)).scalars().all())
        for user_id in user_ids:
            if user_id in existing_ids:
                continue
            self.session.add(
                CommunityMembership(
                    community_id=community_id,
                    user_id=user_id,
                    added_via=added_via,
                    added_from_course_id=added_from_course_id,
                )
            )
        await self.session.flush()

    async def list_membership_rows(
        self, community_id: uuid.UUID, pagination: PaginationParams
    ) -> tuple[Sequence[CommunityMembership], int]:
        stmt = (
            self._base_select()
            .where(CommunityMembership.community_id == community_id)
            .order_by(CommunityMembership.created_at.desc())
        )
        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total

    async def remove_membership(self, community_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        membership = await self.get_membership(community_id, user_id)
        if membership is None:
            return False
        await self.hard_delete(membership)
        return True


class CommunityReadRepository(BaseRepository[CommunityRead]):
    """Tracks per (community, user) read markers. No soft-delete concept here -
    a read marker is a pure timestamp, there's nothing to "restore"."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CommunityRead)

    async def get_read(self, community_id: uuid.UUID, user_id: uuid.UUID) -> CommunityRead | None:
        stmt = select(CommunityRead).where(
            CommunityRead.community_id == community_id, CommunityRead.user_id == user_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def mark_read(self, community_id: uuid.UUID, user_id: uuid.UUID, when: datetime) -> CommunityRead:
        existing = await self.get_read(community_id, user_id)
        if existing is not None:
            existing.last_read_at = when
            await self.session.flush()
            return existing
        record = CommunityRead(community_id=community_id, user_id=user_id, last_read_at=when)
        self.session.add(record)
        await self.session.flush()
        return record
