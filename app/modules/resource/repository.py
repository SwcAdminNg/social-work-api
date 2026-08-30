import uuid
from typing import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_repository import BaseRepository
from app.common.pagination import PaginationParams
from app.modules.resource.dto import ResourceFilterParams, ResourceManageFilterParams
from app.modules.resource.entity import Resource


class ResourceRepository(BaseRepository[Resource]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Resource)

    async def get_by_slug(self, slug: str) -> Resource | None:
        stmt = self._base_select().where(Resource.slug == slug)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    def _apply_filters(self, stmt, filters: ResourceFilterParams | None):
        if filters is None:
            return stmt
        if filters.category is not None:
            stmt = stmt.where(Resource.category == filters.category)
        if filters.course_id is not None:
            stmt = stmt.where(Resource.course_id == filters.course_id)
        if filters.search:
            term = f"%{filters.search}%"
            stmt = stmt.where(or_(Resource.name.ilike(term), Resource.description.ilike(term)))
        return stmt

    async def list_published(
        self, pagination: PaginationParams, filters: ResourceFilterParams | None = None
    ) -> tuple[Sequence[Resource], int]:
        stmt = self._base_select().where(Resource.is_published.is_(True))
        stmt = self._apply_filters(stmt, filters)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(Resource.created_at.desc()).offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total

    async def list_manage(
        self,
        pagination: PaginationParams,
        filters: ResourceManageFilterParams | None,
        viewer_id: uuid.UUID | None,
        viewer_is_admin: bool,
    ) -> tuple[Sequence[Resource], int]:
        stmt = self._base_select()
        if not viewer_is_admin and viewer_id is not None:
            from app.modules.course.entity import Course

            owned_course_ids = select(Course.id).where(Course.instructor_id == viewer_id)
            stmt = stmt.where(or_(Resource.owner_id == viewer_id, Resource.course_id.in_(owned_course_ids)))
        stmt = self._apply_filters(stmt, filters)
        if filters is not None and filters.is_published is not None:
            stmt = stmt.where(Resource.is_published == filters.is_published)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(Resource.created_at.desc()).offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total
