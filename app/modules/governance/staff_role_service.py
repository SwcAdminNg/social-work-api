import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.course.repository import CourseRepository
from app.modules.governance.audit_service import AuditEntityTypeEnum, AuditService
from app.modules.governance.dto import StaffRoleGrantDTO
from app.modules.governance.entity import StaffRoleAssignment
from app.modules.governance.permission_service import PermissionService
from app.modules.governance.permissions import PermissionEnum
from app.modules.notification.entity import NotificationTypeEnum
from app.modules.notification.service import NotificationService
from app.modules.user.entity import User
from app.modules.user.repository import UserRepository

logger = logging.getLogger(__name__)


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
