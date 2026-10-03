import enum
import logging
import uuid
from datetime import datetime, timezone
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.modules.course.entity import Course
from app.modules.course.repository import CourseRepository
from app.modules.governance.audit_service import AuditEntityTypeEnum, AuditService
from app.modules.governance.dto import (
    StaffMemberDTO,
    StaffMemberRolesDTO,
    StaffRoleAssignmentReadDTO,
    StaffRoleCourseRefDTO,
    StaffRoleGrantDTO,
    StaffRoleGrantViewDTO,
)
from app.modules.governance.entity import StaffRoleAssignment
from app.modules.governance.permission_service import PermissionService
from app.modules.governance.permissions import PermissionEnum, StaffRoleEnum
from app.modules.governance.presenter import UserDirectory
from app.modules.notification.entity import NotificationTypeEnum
from app.modules.notification.service import NotificationService
from app.modules.user.entity import User
from app.modules.user.repository import UserRepository

logger = logging.getLogger(__name__)


class StaffRoleStatusEnum(str, enum.Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    ALL = "ALL"


class StaffRoleService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.permissions = PermissionService(session)
        self.audit = AuditService(session)

    async def grant(self, payload: StaffRoleGrantDTO, actor: User) -> StaffRoleAssignment:
        await self.permissions.ensure(actor, PermissionEnum.MANAGE_STAFF_ROLES)

        user = await UserRepository(self.session).get_by_id(payload.user_id)
        if user is None or not user.is_active:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
        if payload.course_id is not None and await CourseRepository(self.session).get_by_id(payload.course_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
        if payload.expires_at is not None and payload.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "expires_at must be in the future")

        existing_stmt = select(StaffRoleAssignment).where(
            StaffRoleAssignment.user_id == payload.user_id,
            StaffRoleAssignment.role == payload.role,
            StaffRoleAssignment.course_id.is_(None)
            if payload.course_id is None
            else StaffRoleAssignment.course_id == payload.course_id,
            StaffRoleAssignment.revoked_at.is_(None),
            StaffRoleAssignment.deleted_at.is_(None),
        )
        if (await self.session.execute(existing_stmt)).scalar_one_or_none() is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "This user already holds that role for that scope")

        assignment = StaffRoleAssignment(
            user_id=payload.user_id,
            role=payload.role,
            course_id=payload.course_id,
            granted_by=actor.id,
            reason=payload.reason,
            expires_at=payload.expires_at,
            created_by=actor.id,
        )
        self.session.add(assignment)
        await self.session.flush()
        self.audit.record(
            actor_id=actor.id,
            action="STAFF_ROLE_GRANTED",
            entity_type=AuditEntityTypeEnum.STAFF_ROLE,
            entity_id=assignment.id,
            course_id=payload.course_id,
            comment=payload.reason,
            actor_permissions=await self.permissions.permissions(actor),
            metadata={"user_id": str(payload.user_id), "role": payload.role.value},
        )
        await self.session.commit()
        await self.session.refresh(assignment)

        await self._notify(user, f"You were given the {_label(payload.role.value)} role", payload.course_id)
        return assignment

    async def revoke(self, assignment_id: uuid.UUID, reason: str | None, actor: User) -> StaffRoleAssignment:
        await self.permissions.ensure(actor, PermissionEnum.MANAGE_STAFF_ROLES)
        assignment = await self.session.get(StaffRoleAssignment, assignment_id)
        if assignment is None or assignment.deleted_at is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Role assignment not found")
        if assignment.revoked_at is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Role assignment is already revoked")

        assignment.revoked_at = datetime.now(timezone.utc)
        assignment.revoked_by = actor.id
        assignment.revoke_reason = reason
        assignment.updated_by = actor.id
        self.audit.record(
            actor_id=actor.id,
            action="STAFF_ROLE_REVOKED",
            entity_type=AuditEntityTypeEnum.STAFF_ROLE,
            entity_id=assignment.id,
            course_id=assignment.course_id,
            comment=reason,
            actor_permissions=await self.permissions.permissions(actor),
            metadata={"user_id": str(assignment.user_id), "role": assignment.role.value},
        )
        await self.session.commit()
        await self.session.refresh(assignment)

        user = await UserRepository(self.session).get_by_id(assignment.user_id)
        if user is not None:
            await self._notify(user, f"Your {_label(assignment.role.value)} role was removed", assignment.course_id)
        return assignment

    # -- read models for the admin UI ------------------------------------------------

    async def present(self, rows: Sequence[StaffRoleAssignment]) -> list[StaffRoleGrantViewDTO]:
        """Attach user and course names to grants, batch-loading both (no N+1)."""
        users = UserDirectory(self.session)
        await users.load([r.user_id for r in rows] + [r.granted_by for r in rows])
        course_ids = {r.course_id for r in rows if r.course_id is not None}
        courses: dict[uuid.UUID, str] = {}
        if course_ids:
            result = await self.session.execute(select(Course.id, Course.title).where(Course.id.in_(course_ids)))
            courses = {row.id: row.title for row in result}
        return [
            StaffRoleGrantViewDTO(
                **StaffRoleAssignmentReadDTO.model_validate(r).model_dump(),
                user=users.get(r.user_id),
                course=StaffRoleCourseRefDTO(id=r.course_id, title=courses[r.course_id])
                if r.course_id in courses
                else None,
                granted_by_user=users.get(r.granted_by),
            )
            for r in rows
        ]

    async def list_members(
        self,
        pagination: PaginationParams,
        search: str | None = None,
        role: StaffRoleEnum | None = None,
        course_id: uuid.UUID | None = None,
        status: StaffRoleStatusEnum = StaffRoleStatusEnum.ACTIVE,
    ) -> tuple[list[StaffMemberRolesDTO], int]:
        """Grants grouped by person, so each staff member appears once with all of
        their roles. Filters narrow both which people match and which grants show;
        pagination is over people, not grants."""
        grant_filters = [StaffRoleAssignment.deleted_at.is_(None)]
        if status == StaffRoleStatusEnum.ACTIVE:
            grant_filters.append(StaffRoleAssignment.revoked_at.is_(None))
        elif status == StaffRoleStatusEnum.REVOKED:
            grant_filters.append(StaffRoleAssignment.revoked_at.is_not(None))
        if role is not None:
            grant_filters.append(StaffRoleAssignment.role == role)
        if course_id is not None:
            grant_filters.append(StaffRoleAssignment.course_id == course_id)

        holders = select(StaffRoleAssignment.user_id).where(*grant_filters).distinct()
        people = select(User).where(User.id.in_(holders), User.deleted_at.is_(None))
        if search and search.strip():
            term = f"%{search.strip()}%"
            people = people.where(
                or_(
                    User.first_name.ilike(term),
                    User.last_name.ilike(term),
                    (User.first_name + " " + User.last_name).ilike(term),
                    User.email.ilike(term),
                    User.username.ilike(term),
                )
            )

        total = (await self.session.execute(select(func.count()).select_from(people.subquery()))).scalar_one()
        page_users = (
            (
                await self.session.execute(
                    people.order_by(User.first_name, User.last_name, User.id)
                    .offset(pagination.offset)
                    .limit(pagination.limit)
                )
            )
            .scalars()
            .all()
        )
        if not page_users:
            return [], total

        grants = (
            (
                await self.session.execute(
                    select(StaffRoleAssignment).where(
                        *grant_filters, StaffRoleAssignment.user_id.in_([u.id for u in page_users])
                    )
                )
            )
            .scalars()
            .all()
        )
        views = await self.present(grants)
        by_user: dict[uuid.UUID, list[StaffRoleGrantViewDTO]] = {}
        for view in views:
            by_user.setdefault(view.user_id, []).append(view)

        now = datetime.now(timezone.utc)
        members: list[StaffMemberRolesDTO] = []
        for user in page_users:
            roles = by_user.get(user.id, [])
            # Active first, then platform-wide before course grants, then by course title.
            roles.sort(
                key=lambda g: (
                    g.revoked_at is not None,
                    g.course_id is not None,
                    (g.course.title.lower() if g.course else ""),
                    g.role.value,
                )
            )
            active = [g for g in roles if g.revoked_at is None and (g.expires_at is None or g.expires_at > now)]
            members.append(
                StaffMemberRolesDTO(
                    user=StaffMemberDTO(
                        id=user.id,
                        name=f"{user.first_name} {user.last_name}".strip(),
                        email=user.email,
                        username=user.username,
                        user_type=user.user_type.value,
                        profile_picture_url=user.profile_picture_url,
                    ),
                    roles=roles,
                    active_role_count=len(active),
                    platform_role_count=sum(1 for g in active if g.course_id is None),
                    course_count=len({g.course_id for g in active if g.course_id is not None}),
                )
            )
        return members, total

    async def _notify(self, user: User, title: str, course_id: uuid.UUID | None) -> None:
        scope = "for one course" if course_id else "across the platform"
        try:
            await NotificationService(self.session).notify_many(
                [user.id], NotificationTypeEnum.ROLE_CHANGED, title,
                f"This applies {scope}.", "/dashboard/approval-centre",
                {"course_id": str(course_id) if course_id else None},
            )
        except Exception as exc:  # a notification failure must never undo the grant
            logger.warning("Failed to notify user %s of a role change: %s", user.id, exc)


def _label(value: str) -> str:
    return value.replace("_", " ").title()
