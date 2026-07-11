import uuid
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.common.slug import ensure_unique_slug, slugify
from app.core.storage import get_r2_client
from app.core.cache import get_cache, set_cache, delete_cache
from app.modules.course.dto import (
    CourseCreateDTO,
    CourseFilterParams,
    CourseManageFilterParams,
    CourseThumbnailUploadRequest,
    CourseThumbnailUploadResponse,
    CourseUpdateDTO,
    CourseCatalogCreateDTO,
    CourseCatalogUpdateDTO,
    PublicCourseCatalogReadDTO,
)
from app.modules.course.entity import Course, CourseItem, CourseSection, CourseCatalog
from app.modules.course.repository import CourseRepository, CourseCatalogRepository
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
        filter_parts = []
        if filters:
            if filters.category: filter_parts.append(f"cat_{filters.category.value if hasattr(filters.category, 'value') else filters.category}")
            if filters.level: filter_parts.append(f"lvl_{filters.level.value if hasattr(filters.level, 'value') else filters.level}")
            if filters.is_free is not None: filter_parts.append(f"free_{filters.is_free}")
            if filters.search: filter_parts.append(f"search_{filters.search}")
            if hasattr(filters, 'catalog') and filters.catalog: filter_parts.append(f"catalog_{filters.catalog}")
            
        filters_key = ":".join(filter_parts) if filter_parts else "all"
        cache_key = f"courses:published:page_{pagination.page}:size_{pagination.page_size}:filters_{filters_key}"
        
        cached_data = await get_cache(cache_key)
        if cached_data:
            items = [Course(**item) for item in cached_data['items']]
            return items, cached_data['total']

        catalog_categories = None
        if filters and hasattr(filters, 'catalog') and filters.catalog:
            catalog_repo = CourseCatalogRepository(self.session)
            catalog = await catalog_repo.get_by_slug(filters.catalog)
            if catalog:
                catalog_categories = catalog.categories
            else:
                return [], 0 # If catalog not found, return empty
                
        items, total = await self.repository.list_published(pagination, filters, catalog_categories)
        
        from app.modules.course.dto import CourseReadDTO
        serializable_items = [CourseReadDTO.model_validate(item).model_dump(mode='json') for item in items]
        await set_cache(cache_key, {'items': serializable_items, 'total': total}, expire=1200)
        
        return items, total

    async def list_enrolled(
        self, current_user: User, pagination: PaginationParams
    ) -> tuple[Sequence[Course], int]:
        return await self.repository.list_enrolled(current_user.id, pagination)

    async def list_manage(
        self, pagination: PaginationParams, filters: CourseManageFilterParams, current_user: User
    ) -> tuple[Sequence[Course], int]:
        instructor_id = None if current_user.user_type == UserTypeEnum.ADMIN else current_user.id
        return await self.repository.list_manage(pagination, filters, instructor_id)

    async def get_by_slug_published(self, slug: str) -> Course:
        cache_key = f"course:slug:{slug}"
        cached_course = await get_cache(cache_key)
        if cached_course:
            # Reconstruct course object
            return Course(**cached_course)

        course = await self.repository.get_by_slug(slug)
        if course is None or not course.is_published:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
            
        # Serialize for cache using its schema model
        from app.modules.course.dto import CourseReadDTO
        await set_cache(cache_key, CourseReadDTO.model_validate(course).model_dump(mode='json'), expire=900)
        
        return course

    async def get_by_id(self, id: uuid.UUID) -> Course:
        course = await self.repository.get_by_id(id)
        if course is None:
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
        
        await delete_cache(f"course:slug:{course.slug}")
        await delete_cache("courses:*")
        
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
        
        await delete_cache(f"course:slug:{course.slug}")
        await delete_cache("courses:*")
        await delete_cache("course_catalogs:public")
        await delete_cache("home:stats")
        
        return course

    async def delete(self, id: uuid.UUID, current_user: User) -> None:
        course = await self.get_for_manage(id, current_user)
        await self.repository.soft_delete(course, current_user.id)
        await self.session.commit()
        
        await delete_cache(f"course:slug:{course.slug}")
        await delete_cache("courses:*")
        await delete_cache("course_catalogs:public")
        await delete_cache("home:stats")

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

    async def get_course_access_details(self, user: User, course_ids: Sequence[uuid.UUID]) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
        if not course_ids:
            return set(), set()
            
        from app.modules.course.access_entity import UserCourseAccess
        from app.modules.payment.entity import UserSubscription
        from datetime import datetime, timezone

        has_sub = False
        now = datetime.now(timezone.utc)
        sub_stmt = select(func.count()).select_from(UserSubscription).where(
            UserSubscription.user_id == user.id,
            UserSubscription.is_active.is_(True),
            UserSubscription.start_date <= now,
            UserSubscription.end_date >= now
        )
        if (await self.session.execute(sub_stmt)).scalar_one() > 0:
            has_sub = True

        enrolled = set()
        accessible = set()
        
        access_stmt = select(UserCourseAccess.course_id).where(
            UserCourseAccess.user_id == user.id, UserCourseAccess.course_id.in_(course_ids)
        )
        enrolled.update((await self.session.execute(access_stmt)).scalars().all())
        accessible.update(enrolled)

        if has_sub:
            stmt = select(Course.id).where(Course.id.in_(course_ids), Course.is_exclusive.is_(False))
            accessible.update((await self.session.execute(stmt)).scalars().all())
        
        return enrolled, accessible

    async def set_featured_courses(self, course_ids: list[uuid.UUID], current_user: User) -> None:
        if current_user.user_type != UserTypeEnum.ADMIN:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can set featured courses")
        await self.repository.set_featured(course_ids)
        await self.session.commit()
        await delete_cache("courses:featured:*")

    async def list_featured_courses(self, pagination: PaginationParams) -> tuple[Sequence[Course], int]:
        cache_key = f"courses:featured:page_{pagination.page}:size_{pagination.page_size}"
        cached_data = await get_cache(cache_key)
        if cached_data:
            items = [Course(**item) for item in cached_data['items']]
            return items, cached_data['total']

        items, total = await self.repository.list_featured(pagination)
        
        # Cache serialization
        from app.modules.course.dto import CourseReadDTO
        serializable_items = [CourseReadDTO.model_validate(item).model_dump(mode='json') for item in items]
        await set_cache(cache_key, {'items': serializable_items, 'total': total}, expire=1800)
        
        return items, total

class CourseCatalogService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = CourseCatalogRepository(session)

    async def create(self, payload: CourseCatalogCreateDTO) -> CourseCatalog:
        slug = await ensure_unique_slug(self.session, CourseCatalog, slugify(payload.name))
        catalog = CourseCatalog(
            name=payload.name, 
            slug=slug, 
            categories=payload.categories,
            icon_name=payload.icon_name,
            description=payload.description
        )
        await self.repository.create(catalog)
        await self.session.commit()
        await delete_cache("course_catalogs:public")
        return catalog

    async def list_catalogs_public(self) -> list[PublicCourseCatalogReadDTO]:
        cache_key = "course_catalogs:public"
        cached_catalogs = await get_cache(cache_key)
        if cached_catalogs:
            return [PublicCourseCatalogReadDTO(**catalog) for catalog in cached_catalogs]

        stmt_catalogs = select(CourseCatalog)
        catalogs = (await self.session.execute(stmt_catalogs)).scalars().all()
        
        stmt = select(Course.category, func.count(Course.id)).where(Course.is_published.is_(True)).group_by(Course.category)
        counts = (await self.session.execute(stmt)).all()
        count_map = {row[0].name if hasattr(row[0], 'name') else row[0]: row[1] for row in counts}

        dtos = []
        for catalog in catalogs:
            total_courses = sum(count_map.get(cat.name if hasattr(cat, 'name') else cat, 0) for cat in catalog.categories)
            dtos.append(
                PublicCourseCatalogReadDTO(
                    id=catalog.id,
                    created_at=catalog.created_at,
                    updated_at=catalog.updated_at,
                    name=catalog.name,
                    slug=catalog.slug,
                    categories=catalog.categories,
                    icon_name=catalog.icon_name,
                    description=catalog.description,
                    total_courses=total_courses
                )
            )
            
        serializable_catalogs = [catalog.model_dump(mode='json') for catalog in dtos]
        await set_cache(cache_key, serializable_catalogs, expire=3600)
        
        return dtos
