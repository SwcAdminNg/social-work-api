import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.course.entity import Course
from app.modules.governance.entity import StaffRoleAssignment
from app.modules.governance.permissions import (
    ALL_PERMISSIONS,
    ROLE_PERMISSIONS,
    PermissionEnum,
    StaffRoleEnum,
    roles_granting,
)
from app.modules.user.entity import User, UserTypeEnum


@dataclass(frozen=True)
class EffectiveRole:
    role: StaffRoleEnum
    course_id: uuid.UUID | None
    # True when derived from the account type / course ownership rather than a
    # staff_role_assignments row - implicit roles can't be revoked individually.
    implicit: bool
    assignment_id: uuid.UUID | None = None


def _active_assignment_filter(now: datetime):
    return (
        StaffRoleAssignment.revoked_at.is_(None),
        StaffRoleAssignment.deleted_at.is_(None),
        or_(StaffRoleAssignment.expires_at.is_(None), StaffRoleAssignment.expires_at > now),
    )


class PermissionService:
    """Resolves what a user may do, globally or for one course.

    Sources, unioned:
    - explicit `staff_role_assignments` rows (global, or scoped to the course);
    - implicit roles, so existing accounts keep working with no backfill: an
      ADMIN is a PLATFORM_ADMIN everywhere; an INSTRUCTOR may create courses and
      holds the INSTRUCTOR role on courses they own (`Course.instructor_id`).

    While `content_governance_enabled` is off, admins keep every permission -
    exactly the pre-governance behaviour where an admin could do anything."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._assignments: dict[uuid.UUID, list[StaffRoleAssignment]] = {}

    async def _active_assignments(self, user_id: uuid.UUID) -> list[StaffRoleAssignment]:
        if user_id not in self._assignments:
            stmt = select(StaffRoleAssignment).where(
                StaffRoleAssignment.user_id == user_id, *_active_assignment_filter(datetime.now(timezone.utc))
            )
            self._assignments[user_id] = list((await self.session.execute(stmt)).scalars().all())
        return self._assignments[user_id]

    async def effective_roles(self, user: User, course: Course | None = None) -> list[EffectiveRole]:
        roles: list[EffectiveRole] = []
        if user.user_type == UserTypeEnum.ADMIN:
            roles.append(EffectiveRole(StaffRoleEnum.PLATFORM_ADMIN, None, implicit=True))
        if (
            course is not None
            and course.instructor_id == user.id
            and user.user_type in (UserTypeEnum.INSTRUCTOR, UserTypeEnum.ADMIN)
        ):
            roles.append(EffectiveRole(StaffRoleEnum.INSTRUCTOR, course.id, implicit=True))
        for assignment in await self._active_assignments(user.id):
            if assignment.course_id is None or (course is not None and assignment.course_id == course.id):
                roles.append(EffectiveRole(assignment.role, assignment.course_id, implicit=False, assignment_id=assignment.id))
        return roles

    async def permissions(self, user: User, course: Course | None = None) -> set[PermissionEnum]:
        if user.user_type == UserTypeEnum.ADMIN and not settings.content_governance_enabled:
            return set(ALL_PERMISSIONS)
        perms: set[PermissionEnum] = set()
        if user.user_type == UserTypeEnum.INSTRUCTOR:
            perms.add(PermissionEnum.CREATE_CONTENT)
        for role in await self.effective_roles(user, course):
            perms |= ROLE_PERMISSIONS[role.role]
        return perms

    async def has(self, user: User, permission: PermissionEnum, course: Course | None = None) -> bool:
        return permission in await self.permissions(user, course)

    async def ensure(
        self, user: User, permission: PermissionEnum, course: Course | None = None, message: str | None = None
    ) -> None:
        if not await self.has(user, permission, course):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, message or f"Missing permission {permission.value}"
            )

    async def has_anywhere(self, user: User, permission: PermissionEnum) -> bool:
        """True when the user holds `permission` globally or for at least one
        course - the gate for cross-course screens like the Approval Centre."""
        if await self.has(user, permission):
            return True
        if any(
            permission in ROLE_PERMISSIONS[a.role] for a in await self._active_assignments(user.id)
        ):
            return True
        if permission in ROLE_PERMISSIONS[StaffRoleEnum.INSTRUCTOR] and user.user_type in (
            UserTypeEnum.INSTRUCTOR, UserTypeEnum.ADMIN
        ):
            stmt = select(Course.id).where(Course.instructor_id == user.id, Course.deleted_at.is_(None)).limit(1)
            return (await self.session.execute(stmt)).first() is not None
        return False

    async def course_ids_with_permission(self, user: User, permission: PermissionEnum) -> list[uuid.UUID]:
        """Courses where the user holds `permission` through a course-scoped
        assignment (global grants and ownership are checked separately)."""
        return [
            a.course_id
            for a in await self._active_assignments(user.id)
            if a.course_id is not None and permission in ROLE_PERMISSIONS[a.role]
        ]

    async def user_ids_with_permission(self, permission: PermissionEnum, course: Course) -> list[uuid.UUID]:
        """Every active user who holds `permission` for `course` - the reviewer
        pool a stage notification goes to. Callers apply separation-of-duties
        exclusions on top."""
        roles = roles_granting(permission)
        now = datetime.now(timezone.utc)
        stmt = (
            select(StaffRoleAssignment.user_id)
            .join(User, User.id == StaffRoleAssignment.user_id)
            .where(
                StaffRoleAssignment.role.in_(roles),
                or_(StaffRoleAssignment.course_id.is_(None), StaffRoleAssignment.course_id == course.id),
                User.is_active.is_(True),
                User.deleted_at.is_(None),
                *_active_assignment_filter(now),
            )
        )
        user_ids: list[uuid.UUID] = list((await self.session.execute(stmt)).scalars().all())

        # Admins hold PLATFORM_ADMIN implicitly - and every permission while
        # governance is switched off.
        if StaffRoleEnum.PLATFORM_ADMIN in roles or not settings.content_governance_enabled:
            admin_stmt = select(User.id).where(
                User.user_type == UserTypeEnum.ADMIN, User.is_active.is_(True), User.deleted_at.is_(None)
            )
            user_ids.extend((await self.session.execute(admin_stmt)).scalars().all())
        if StaffRoleEnum.INSTRUCTOR in roles:
            user_ids.append(course.instructor_id)
        return list(dict.fromkeys(user_ids))

    # -- assignments (admin management) -----------------------------------------

    async def list_assignments(
        self,
        user_id: uuid.UUID | None = None,
        role: StaffRoleEnum | None = None,
        course_id: uuid.UUID | None = None,
        include_revoked: bool = False,
    ) -> Sequence[StaffRoleAssignment]:
        stmt = select(StaffRoleAssignment).where(StaffRoleAssignment.deleted_at.is_(None))
        if not include_revoked:
            stmt = stmt.where(StaffRoleAssignment.revoked_at.is_(None))
        if user_id is not None:
            stmt = stmt.where(StaffRoleAssignment.user_id == user_id)
        if role is not None:
            stmt = stmt.where(StaffRoleAssignment.role == role)
        if course_id is not None:
            stmt = stmt.where(StaffRoleAssignment.course_id == course_id)
        stmt = stmt.order_by(StaffRoleAssignment.created_at.desc())
        return (await self.session.execute(stmt)).scalars().all()
