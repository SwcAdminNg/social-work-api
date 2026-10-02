import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.course.repository import CourseRepository
from app.modules.governance.permission_service import PermissionService
from app.modules.governance.permissions import PermissionEnum
from app.modules.user.entity import User, UserTypeEnum


def require_permission(*permissions: PermissionEnum):
    """Route dependency: the user must hold at least one of `permissions`,
    globally or for any course. Use it for cross-course entry points (Approval
    Centre, audit log); per-course checks happen in the service once the course
    is resolved, or via `require_course_permission`."""

    async def dependency(
        current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
    ) -> User:
        service = PermissionService(db)
        for permission in permissions:
            if await service.has_anywhere(current_user, permission):
                return current_user
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Requires one of: {', '.join(p.value for p in permissions)}"
        )

    return dependency


def require_course_permission(permission: PermissionEnum):
    """Route dependency for routes with a `course_id` path parameter."""

    async def dependency(
        course_id: uuid.UUID,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        course = await CourseRepository(db).get_by_id(course_id)
        if course is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
        await PermissionService(db).ensure(current_user, permission, course)
        return current_user

    return dependency


async def get_current_content_staff(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> User:
    """Gate for course-authoring routes: admins and instructors as before, plus
    any account holding a governance staff role (e.g. a Content Developer or
    Course Lead on a plain user account). Per-course permission checks still
    happen in the services."""
    if current_user.user_type in (UserTypeEnum.ADMIN, UserTypeEnum.INSTRUCTOR):
        return current_user
    if await PermissionService(db).list_assignments(user_id=current_user.id):
        return current_user
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin, instructor or content staff access required")
