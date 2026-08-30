import uuid
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.common.slug import ensure_unique_slug, slugify
from app.core.storage import get_r2_client
from app.modules.course.entity import Course
from app.modules.resource.dto import (
    ResourceCreateDTO,
    ResourceFilterParams,
    ResourceManageFilterParams,
    ResourceThumbnailUploadRequest,
    ResourceThumbnailUploadResponse,
    ResourceUpdateDTO,
)
from app.modules.resource.entity import Resource, ResourceVisibilityEnum
from app.modules.resource.repository import ResourceRepository
from app.modules.user.entity import User, UserTypeEnum

# Fields on the create/update DTOs that don't map to a Resource column.
_NON_COLUMN_FIELDS = {"can_access", "access_reason"}


class ResourceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ResourceRepository(session)

    # -- authorization helpers ------------------------------------------------

    async def _get_course_or_none(self, course_id: uuid.UUID | None) -> Course | None:
        if course_id is None:
            return None
        stmt = select(Course).where(Course.id == course_id, Course.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _ensure_can_tie_to_course(self, course_id: uuid.UUID | None, user: User) -> None:
        """A non-admin can only tie a resource to a course they own."""
        if course_id is None or user.user_type == UserTypeEnum.ADMIN:
            return
        course = await self._get_course_or_none(course_id)
        if course is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
        if course.instructor_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not manage this course")

    async def ensure_can_manage(self, resource: Resource, user: User) -> None:
        if user.user_type == UserTypeEnum.ADMIN:
            return
        if resource.owner_id == user.id:
            return
        course = await self._get_course_or_none(resource.course_id)
        if course is not None and course.instructor_id == user.id:
            return
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not manage this resource")

    # -- CRUD ------------------------------------------------------------------

    async def create(self, payload: ResourceCreateDTO, current_user: User) -> Resource:
        await self._ensure_can_tie_to_course(payload.course_id, current_user)
        slug = await ensure_unique_slug(self.session, Resource, slugify(payload.name))
        resource = Resource(
            **payload.model_dump(exclude=_NON_COLUMN_FIELDS), slug=slug, owner_id=current_user.id
        )
        self.session.add(resource)
        await self.session.flush()
        await self.session.commit()
        return resource

    async def get_by_id(self, id: uuid.UUID) -> Resource:
        resource = await self.repository.get_by_id(id)
        if resource is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found")
        return resource

    async def get_for_manage(self, id: uuid.UUID, current_user: User) -> Resource:
        resource = await self.get_by_id(id)
        await self.ensure_can_manage(resource, current_user)
        return resource

    async def get_by_slug_published(self, slug: str) -> Resource:
        resource = await self.repository.get_by_slug(slug)
        if resource is None or not resource.is_published:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found")
        return resource

    async def update(self, id: uuid.UUID, payload: ResourceUpdateDTO, current_user: User) -> Resource:
        resource = await self.get_for_manage(id, current_user)
        update_data = payload.model_dump(exclude_unset=True, exclude=_NON_COLUMN_FIELDS)

        final_visibility = update_data.get("visibility", resource.visibility)
        final_course_id = update_data.get("course_id", resource.course_id)
        if final_visibility == ResourceVisibilityEnum.COURSE_ENROLLED and final_course_id is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "course_id is required when visibility is COURSE_ENROLLED"
            )
        if "course_id" in update_data:
            await self._ensure_can_tie_to_course(update_data["course_id"], current_user)

        for field, value in update_data.items():
            setattr(resource, field, value)
        await self.repository.update(resource)
        await self.session.commit()
        return resource

    async def delete(self, id: uuid.UUID, current_user: User) -> None:
        resource = await self.get_for_manage(id, current_user)
        await self.repository.soft_delete(resource, current_user.id)
        await self.session.commit()

    async def set_published(self, id: uuid.UUID, is_published: bool, current_user: User) -> Resource:
        resource = await self.get_for_manage(id, current_user)
        resource.is_published = is_published
        await self.repository.update(resource)
        await self.session.commit()
        return resource

    async def generate_thumbnail_upload_url(
        self, id: uuid.UUID, payload: ResourceThumbnailUploadRequest, current_user: User
    ) -> ResourceThumbnailUploadResponse:
        resource = await self.get_for_manage(id, current_user)
        r2_client = get_r2_client()

        if resource.thumbnail_url:
            from app.core.config import settings

            old_key = resource.thumbnail_url.replace(f"{settings.r2_public_url.rstrip('/')}/", "")
            r2_client.delete_object(old_key)

        thumbnail_key = r2_client.build_resource_thumbnail_key(resource.id, payload.file_name)
        upload_url = r2_client.generate_upload_url(thumbnail_key, payload.content_type)

        public_url = r2_client.get_public_url(thumbnail_key)
        resource.thumbnail_url = public_url
        await self.repository.update(resource)
        await self.session.commit()

        return ResourceThumbnailUploadResponse(upload_url=upload_url, thumbnail_url=public_url)

    # -- listing -----------------------------------------------------------------

    async def list_published(
        self, pagination: PaginationParams, filters: ResourceFilterParams | None = None
    ) -> tuple[Sequence[Resource], int]:
        return await self.repository.list_published(pagination, filters)

    async def list_manage(
        self, pagination: PaginationParams, filters: ResourceManageFilterParams, current_user: User
    ) -> tuple[Sequence[Resource], int]:
        is_admin = current_user.user_type == UserTypeEnum.ADMIN
        return await self.repository.list_manage(
            pagination, filters, viewer_id=current_user.id, viewer_is_admin=is_admin
        )

    # -- viewer access resolution -------------------------------------------

    async def resolve_access(self, resource: Resource, user: User | None) -> tuple[bool, str | None]:
        """Whether `user` (possibly None/anonymous) can see this resource's
        attachments, and why not if they can't."""
        if resource.visibility == ResourceVisibilityEnum.PUBLIC:
            return True, None
        if user is None:
            return False, "LOGIN_REQUIRED"
        if resource.visibility == ResourceVisibilityEnum.LOGGED_IN:
            return True, None

        # COURSE_ENROLLED
        if user.user_type == UserTypeEnum.ADMIN or resource.owner_id == user.id:
            return True, None
        if resource.course_id is None:
            return True, None
        course = await self._get_course_or_none(resource.course_id)
        if course is not None and course.instructor_id == user.id:
            return True, None

        from app.modules.course.service import CourseService

        has_access = await CourseService(self.session).check_course_access(resource.course_id, user)
        return has_access, (None if has_access else "ENROLLMENT_REQUIRED")

    async def attach_access(self, dtos, user: User | None) -> None:
        """Mutates a list of ResourceReadDTO (or subclass) in place, filling
        `can_access`/`access_reason`. Batches the "do I own this course" check
        and caches the enrollment check per distinct course id, so a library
        page with many COURSE_ENROLLED resources doesn't re-query per row."""
        if not dtos:
            return

        owned_course_ids: set[uuid.UUID] = set()
        if user is not None:
            owned_stmt = select(Course.id).where(Course.instructor_id == user.id)
            owned_course_ids = set((await self.session.execute(owned_stmt)).scalars().all())

        course_access_cache: dict[uuid.UUID, bool] = {}
        from app.modules.course.service import CourseService

        for dto in dtos:
            if dto.visibility == ResourceVisibilityEnum.PUBLIC:
                dto.can_access, dto.access_reason = True, None
                continue
            if user is None:
                dto.can_access, dto.access_reason = False, "LOGIN_REQUIRED"
                continue
            if dto.visibility == ResourceVisibilityEnum.LOGGED_IN:
                dto.can_access, dto.access_reason = True, None
                continue

            # COURSE_ENROLLED
            if (
                user.user_type == UserTypeEnum.ADMIN
                or dto.owner_id == user.id
                or (dto.course_id is not None and dto.course_id in owned_course_ids)
                or dto.course_id is None
            ):
                dto.can_access, dto.access_reason = True, None
                continue

            if dto.course_id not in course_access_cache:
                course_access_cache[dto.course_id] = await CourseService(self.session).check_course_access(
                    dto.course_id, user
                )
            has_access = course_access_cache[dto.course_id]
            dto.can_access = has_access
            dto.access_reason = None if has_access else "ENROLLMENT_REQUIRED"
