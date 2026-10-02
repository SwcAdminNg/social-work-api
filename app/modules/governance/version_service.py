import uuid
from datetime import datetime, timezone
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.course.entity import Course
from app.modules.governance.audit_service import AuditEntityTypeEnum, AuditService
from app.modules.governance.draft_scope import include_drafts
from app.modules.governance.entity import CourseVersion
from app.modules.governance.enums import CourseLifecycleEnum
from app.modules.governance.tree import build_normalized_tree, tree_hash
from app.modules.user.entity import User


class VersionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_versions(self, course_id: uuid.UUID) -> Sequence[CourseVersion]:
        stmt = (
            select(CourseVersion)
            .where(CourseVersion.course_id == course_id, CourseVersion.deleted_at.is_(None))
            .order_by(CourseVersion.major.desc(), CourseVersion.minor.desc())
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def get_version(self, course_id: uuid.UUID, version_id: uuid.UUID) -> CourseVersion:
        version = await self.session.get(CourseVersion, version_id)
        if version is None or version.course_id != course_id or version.deleted_at is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
        return version

    async def record_legacy_publish(self, course: Course, actor: User) -> CourseVersion | None:
        """Governance switched off: publishing is still the old owner/admin
        toggle, but every publish whose content differs from the current version
        is captured as a new minor version so history accrues from day one."""
        with include_drafts(self.session):
            snapshot = await build_normalized_tree(self.session, course)
        digest = tree_hash(snapshot)

        current = await self.session.get(CourseVersion, course.current_version_id) if course.current_version_id else None
        if current is not None and current.snapshot_hash == digest:
            return None
        if current is not None and current.snapshot is None:
            # Pre-governance baseline never captured: this publish *is* its content.
            current.snapshot = snapshot
            current.snapshot_hash = digest
            return current

        now = datetime.now(timezone.utc)
        major, minor = (1, 0) if current is None else (current.major, current.minor + 1)
        version = CourseVersion(
            course_id=course.id,
            major=major,
            minor=minor,
            label=f"{major}.{minor}",
            snapshot=snapshot,
            snapshot_hash=digest,
            author_id=course.instructor_id,
            approved_at=None,
            published_at=now,
            published_by=actor.id,
            reason="Published without governance review",
            risk_level=None,
            is_current=True,
            created_by=actor.id,
        )
        if current is not None:
            current.is_current = False
        self.session.add(version)
        await self.session.flush()
        course.current_version_id = version.id
        course.current_version_label = version.label
        AuditService(self.session).record(
            actor_id=actor.id,
            action="LEGACY_PUBLISHED",
            entity_type=AuditEntityTypeEnum.COURSE_VERSION,
            entity_id=version.id,
            course_id=course.id,
            version_label=version.label,
            to_status=CourseLifecycleEnum.PUBLISHED,
            comment="Published while content governance was switched off",
        )
        return version

    def record_legacy_lifecycle(self, course: Course, actor: User, published: bool) -> None:
        previous = course.governance_status
        course.governance_status = CourseLifecycleEnum.PUBLISHED if published else CourseLifecycleEnum.DRAFT
        if previous != course.governance_status:
            AuditService(self.session).record(
                actor_id=actor.id,
                action="LEGACY_PUBLISH_TOGGLED",
                entity_type=AuditEntityTypeEnum.COURSE,
                entity_id=course.id,
                course_id=course.id,
                version_label=course.current_version_label,
                from_status=previous,
                to_status=course.governance_status,
            )

