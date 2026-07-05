import uuid
from typing import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_repository import BaseRepository
from app.common.pagination import PaginationParams
from app.modules.course.dto import CourseFilterParams, CourseManageFilterParams
from app.modules.course.entity import Course


class CourseRepository(BaseRepository[Course]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Course)

    async def get_by_slug(self, slug: str) -> Course | None:
        stmt = self._base_select().where(Course.slug == slug)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    def _apply_filters(self, stmt, filters: CourseFilterParams | None):
        if filters is None:
            return stmt
        if filters.category is not None:
            stmt = stmt.where(Course.category == filters.category)
        if filters.level is not None:
            stmt = stmt.where(Course.level == filters.level)
        if filters.is_free is not None:
            stmt = stmt.where(Course.is_free == filters.is_free)
        if filters.search is not None:
            term = f"%{filters.search}%"
            stmt = stmt.where(or_(Course.title.ilike(term), Course.description.ilike(term)))
        return stmt

    async def list_published(
        self, pagination: PaginationParams, filters: CourseFilterParams | None = None
    ) -> tuple[Sequence[Course], int]:
        stmt = self._base_select().where(Course.is_published.is_(True))
        stmt = self._apply_filters(stmt, filters)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total

    async def list_manage(
        self,
        pagination: PaginationParams,
        filters: CourseManageFilterParams | None = None,
        instructor_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[Course], int]:
        stmt = self._base_select()
        if instructor_id is not None:
            stmt = stmt.where(Course.instructor_id == instructor_id)
        stmt = self._apply_filters(stmt, filters)
        if filters is not None and filters.is_published is not None:
            stmt = stmt.where(Course.is_published == filters.is_published)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total

    async def list_enrolled(
        self, user_id: uuid.UUID, pagination: PaginationParams
    ) -> tuple[Sequence[Course], int]:
        from app.modules.course.access_entity import UserCourseAccess
        
        stmt = (
            self._base_select()
            .join(UserCourseAccess, UserCourseAccess.course_id == Course.id)
            .where(UserCourseAccess.user_id == user_id)
        )
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total
