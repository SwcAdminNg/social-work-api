import uuid
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.common.slug import ensure_unique_slug, slugify
from app.core.storage import get_r2_client
from app.modules.course.dto import (
    CourseCreateDTO,
    CourseFilterParams,
    CourseManageFilterParams,
    CourseThumbnailUploadRequest,
    CourseThumbnailUploadResponse,
    CourseUpdateDTO,
)
from app.modules.course.entity import Course, CourseItem, CourseSection
from app.modules.course.repository import CourseRepository
from app.modules.user.entity import User, UserTypeEnum


class CourseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = CourseRepository(session)

    def ensure_can_manage(self, course: Course, user: User) -> None:
        if user.user_type != UserTypeEnum.ADMIN and course.instructor_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not manage this course")

    async def create(self, payload: CourseCreateDTO, instructor: User) -> Course:
        slug = await ensure_unique_slug(self.session, Course, slugify(payload.title))
        course = Course(**payload.model_dump(), slug=slug, instructor_id=instructor.id)
        await self.repository.create(course)
        await self.session.commit()
        return course

    async def list_published(
        self, pagination: PaginationParams, filters: CourseFilterParams | None = None
    ) -> tuple[Sequence[Course], int]:
        return await self.repository.list_published(pagination, filters)

    async def list_manage(
        self, pagination: PaginationParams, filters: CourseManageFilterParams, current_user: User
    ) -> tuple[Sequence[Course], int]:
        instructor_id = None if current_user.user_type == UserTypeEnum.ADMIN else current_user.id
        return await self.repository.list_manage(pagination, filters, instructor_id)

    async def get_by_slug_published(self, slug: str) -> Course:
        course = await self.repository.get_by_slug(slug)
        if course is None or not course.is_published:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
        return course

    async def get_for_manage(self, id: uuid.UUID, current_user: User) -> Course:
        course = await self.repository.get_by_id(id)
        if course is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
        self.ensure_can_manage(course, current_user)
        return course

    async def update(self, id: uuid.UUID, payload: CourseUpdateDTO, current_user: User) -> Course:
        course = await self.get_for_manage(id, current_user)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(course, field, value)
        await self.repository.update(course)
        await self.session.commit()
        return course

    async def set_published(self, id: uuid.UUID, is_published: bool, current_user: User) -> Course:
        course = await self.get_for_manage(id, current_user)
        if is_published:
            item_count_stmt = (
                select(func.count())
                .select_from(CourseItem)
                .join(CourseSection, CourseItem.section_id == CourseSection.id)
                .where(CourseSection.course_id == course.id, CourseItem.deleted_at.is_(None))
            )
            item_count = (await self.session.execute(item_count_stmt)).scalar_one()
            if item_count == 0:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Course must have at least one curriculum item before publishing",
                )
        course.is_published = is_published
        await self.repository.update(course)
        await self.session.commit()
        return course

    async def delete(self, id: uuid.UUID, current_user: User) -> None:
        course = await self.get_for_manage(id, current_user)
        await self.repository.soft_delete(course, current_user.id)
        await self.session.commit()

    async def generate_thumbnail_upload_url(
        self, course_id: uuid.UUID, payload: CourseThumbnailUploadRequest, current_user: User
    ) -> CourseThumbnailUploadResponse:
        course = await self.get_for_manage(course_id, current_user)
        r2_client = get_r2_client()

        if course.thumbnail_url:
            from app.core.config import settings
            old_key = course.thumbnail_url.replace(f"{settings.r2_public_url.rstrip('/')}/", "")
            r2_client.delete_object(old_key)

        thumbnail_key = r2_client.build_thumbnail_key(course.id, payload.file_name)
        upload_url = r2_client.generate_upload_url(thumbnail_key, payload.content_type)
        
        public_url = r2_client.get_public_url(thumbnail_key)
        course.thumbnail_url = public_url
        await self.repository.update(course)
        await self.session.commit()
        
        return CourseThumbnailUploadResponse(upload_url=upload_url, thumbnail_url=public_url)

    async def check_course_access(self, course_id: uuid.UUID, user: User) -> bool:
        from app.modules.course.access_entity import UserCourseAccess
        from app.modules.payment.entity import UserSubscription
        from datetime import datetime, timezone

        # 1. Direct access check
        direct_access_stmt = select(func.count()).select_from(UserCourseAccess).where(
            UserCourseAccess.user_id == user.id, UserCourseAccess.course_id == course_id
        )
        direct_access = (await self.session.execute(direct_access_stmt)).scalar_one()
        if direct_access > 0:
            return True
            
        course = await self.repository.get_by_id(course_id)
        if not course or course.is_exclusive:
            return False

        # 2. Subscription access check
        now = datetime.now(timezone.utc)
        sub_stmt = select(func.count()).select_from(UserSubscription).where(
            UserSubscription.user_id == user.id,
            UserSubscription.is_active.is_(True),
            UserSubscription.start_date <= now,
            UserSubscription.end_date >= now
        )
        sub_count = (await self.session.execute(sub_stmt)).scalar_one()
        return sub_count > 0
