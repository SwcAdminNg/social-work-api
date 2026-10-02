"""Grants the first governance roles, so an environment can switch content
governance on without the chicken-and-egg of needing a role to grant roles.

Platform admins already get PLATFORM_ADMIN implicitly and can grant every other
role through POST /admin/staff-roles; this script is for setting up the
academic side (Head of Learning, reviewers) from a deploy shell. Each grant is
written to the governance audit log.

Idempotent: an active grant of the same role and scope is left as is.

Usage:
    python -m app.scripts.bootstrap_governance HEAD_OF_LEARNING director@example.org
    python -m app.scripts.bootstrap_governance ACADEMIC_REVIEWER a@example.org b@example.org
    python -m app.scripts.bootstrap_governance COURSE_LEAD lead@example.org --course <course-uuid>
"""

import argparse
import asyncio
import uuid

from sqlalchemy import func, select

import app.models  # noqa: F401 - registers every entity on Base.metadata before use
from app.core.database import AsyncSessionLocal
from app.modules.governance.audit_service import AuditEntityTypeEnum, AuditService
from app.modules.governance.entity import StaffRoleAssignment
from app.modules.governance.permissions import StaffRoleEnum
from app.modules.user.entity import User


async def main(role: StaffRoleEnum, emails: list[str], course_id: uuid.UUID | None) -> None:
    async with AsyncSessionLocal() as session:
        for email in emails:
            user = (
                await session.execute(select(User).where(func.lower(User.email) == email.lower()))
            ).scalar_one_or_none()
            if user is None:
                print(f"  no user with email {email} - skipped")
                continue
            existing = (
                await session.execute(
                    select(StaffRoleAssignment).where(
                        StaffRoleAssignment.user_id == user.id,
                        StaffRoleAssignment.role == role,
                        StaffRoleAssignment.course_id.is_(None)
                        if course_id is None
                        else StaffRoleAssignment.course_id == course_id,
                        StaffRoleAssignment.revoked_at.is_(None),
                        StaffRoleAssignment.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                print(f"  {email} already holds {role.value}")
                continue
            assignment = StaffRoleAssignment(
                user_id=user.id, role=role, course_id=course_id, reason="Granted by bootstrap_governance script"
            )
            session.add(assignment)
            await session.flush()
            AuditService(session).record(
                actor_id=None,
                action="STAFF_ROLE_GRANTED",
                entity_type=AuditEntityTypeEnum.STAFF_ROLE,
                entity_id=assignment.id,
                course_id=course_id,
                comment="Granted by bootstrap_governance script",
                metadata={"user_id": str(user.id), "role": role.value},
            )
            await session.commit()
            print(f"  granted {role.value} to {email}" + (f" for course {course_id}" if course_id else ""))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("role", choices=[r.value for r in StaffRoleEnum])
    parser.add_argument("emails", nargs="+")
    parser.add_argument("--course", type=uuid.UUID, default=None, help="Scope the role to one course")
    args = parser.parse_args()
    asyncio.run(main(StaffRoleEnum(args.role), args.emails, args.course))
