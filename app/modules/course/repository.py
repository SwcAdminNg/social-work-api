import uuid
from typing import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_repository import BaseRepository
from app.common.pagination import PaginationParams
from app.modules.course.dto import CourseFilterParams, CourseManageFilterParams, CourseProgressStatusEnum
from app.modules.course.entity import Course, CourseCatalog, CourseItem, CourseSection
from app.modules.course.instructor_entity import CourseInstructor


class CourseRepository(BaseRepository[Course]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Course)

    async def get_by_slug(self, slug: str) -> Course | None:
        stmt = self._base_select().where(Course.slug == slug)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def sum_estimated_minutes_by_course(self, course_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not course_ids:
            return {}
        stmt = (
            select(CourseSection.course_id, func.coalesce(func.sum(CourseItem.estimated_minutes), 0))
            .select_from(CourseItem)
            .join(CourseSection, CourseItem.section_id == CourseSection.id)
            .where(
                CourseSection.course_id.in_(course_ids),
                CourseItem.deleted_at.is_(None),
                CourseSection.deleted_at.is_(None),
            )
            .group_by(CourseSection.course_id)
        )
        rows = (await self.session.execute(stmt)).all()
        return {row[0]: int(row[1]) for row in rows}

    def _apply_filters(self, stmt, filters: CourseFilterParams | None, catalog_categories: list[str] | None = None):
        if filters is None:
            if catalog_categories is not None:
                stmt = stmt.where(Course.category.in_(catalog_categories))
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
        if getattr(filters, "instructor_id", None) is not None:
            co_instructor_stmt = select(CourseInstructor.course_id).where(
                CourseInstructor.user_id == filters.instructor_id
            )
            stmt = stmt.where(
                or_(Course.instructor_id == filters.instructor_id, Course.id.in_(co_instructor_stmt))
            )
        if getattr(filters, "instructor_name", None) is not None:
            name_term = f"%{filters.instructor_name}%"
            name_match_stmt = select(CourseInstructor.course_id).where(
                CourseInstructor.name.ilike(name_term)
            )
            stmt = stmt.where(Course.id.in_(name_match_stmt))
        if catalog_categories is not None:
            stmt = stmt.where(Course.category.in_(catalog_categories))
        return stmt

    async def list_published(
        self, pagination: PaginationParams, filters: CourseFilterParams | None = None, catalog_categories: list[str] | None = None
    ) -> tuple[Sequence[Course], int]:
        stmt = self._base_select().where(Course.is_published.is_(True))
        stmt = self._apply_filters(stmt, filters, catalog_categories)

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
        catalog_categories: list[str] | None = None
    ) -> tuple[Sequence[Course], int]:
        stmt = self._base_select()
        if instructor_id is not None:
            stmt = stmt.where(Course.instructor_id == instructor_id)
        stmt = self._apply_filters(stmt, filters, catalog_categories)
        if filters is not None and filters.is_published is not None:
            stmt = stmt.where(Course.is_published == filters.is_published)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total

    async def list_enrolled(
        self,
        user_id: uuid.UUID,
        pagination: PaginationParams,
        search: str | None = None,
        status: CourseProgressStatusEnum | None = None,
    ) -> tuple[Sequence[Course], int]:
        from app.modules.course.access_entity import UserCourseAccess
        from app.modules.learning.entity import UserCourseProgress

        stmt = (
            self._base_select()
            .join(UserCourseAccess, UserCourseAccess.course_id == Course.id)
            .where(UserCourseAccess.user_id == user_id)
        )
        if search:
            term = f"%{search}%"
            name_match_stmt = select(CourseInstructor.course_id).where(CourseInstructor.name.ilike(term))
            stmt = stmt.where(
                or_(Course.title.ilike(term), Course.description.ilike(term), Course.id.in_(name_match_stmt))
            )

        if status is not None:
            stmt = stmt.outerjoin(
                UserCourseProgress,
                (UserCourseProgress.course_id == Course.id) & (UserCourseProgress.user_id == user_id),
            )
            if status == CourseProgressStatusEnum.COMPLETED:
                stmt = stmt.where(UserCourseProgress.is_completed.is_(True))
            elif status == CourseProgressStatusEnum.IN_PROGRESS:
                stmt = stmt.where(
                    UserCourseProgress.is_completed.is_(False), UserCourseProgress.progress_percent > 0
                )
            else:  # NOT_STARTED - no progress row yet, or a row stuck at 0%
                stmt = stmt.where(
                    or_(
                        UserCourseProgress.id.is_(None),
                        (UserCourseProgress.is_completed.is_(False)) & (UserCourseProgress.progress_percent == 0),
                    )
                )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total

    async def list_recent(self, pagination: PaginationParams) -> tuple[Sequence[Course], int]:
        stmt = (
            self._base_select()
            .where(Course.is_published.is_(True))
            .order_by(Course.created_at.desc())
        )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total

    async def list_bookmarked(
        self, user_id: uuid.UUID, pagination: PaginationParams
    ) -> tuple[Sequence[Course], int]:
        from app.modules.course.bookmark_entity import CourseBookmark

        stmt = (
            self._base_select()
            .join(CourseBookmark, CourseBookmark.course_id == Course.id)
            .where(CourseBookmark.user_id == user_id)
            .order_by(CourseBookmark.created_at.desc())
        )
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total

    async def set_featured(self, course_ids: list[uuid.UUID]) -> None:
        from sqlalchemy import update
        # Reset all featured courses
        await self.session.execute(
            update(Course).values(is_featured=False, featured_order=None)
        )
        # Set featured courses in order
        for idx, cid in enumerate(course_ids):
            await self.session.execute(
                update(Course)
                .where(Course.id == cid)
                .values(is_featured=True, featured_order=idx)
            )

    async def list_featured(self, pagination: PaginationParams) -> tuple[Sequence[Course], int]:
        stmt = self._base_select().where(Course.is_featured.is_(True), Course.is_published.is_(True)).order_by(Course.featured_order.asc())
        
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total

class CourseCatalogRepository(BaseRepository[CourseCatalog]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CourseCatalog)

    async def get_by_slug(self, slug: str) -> CourseCatalog | None:
        stmt = self._base_select().where(CourseCatalog.slug == slug)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

