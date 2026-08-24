import uuid
from datetime import datetime
from typing import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_repository import BaseRepository
from app.common.pagination import PaginationParams
from app.modules.certificate.entity import Certificate, CertificateTemplate
from app.modules.course.entity import Course, CourseAccessModeEnum
from app.modules.learning.entity import UserCourseProgress
from app.modules.user.entity import User


class CertificateTemplateRepository(BaseRepository[CertificateTemplate]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CertificateTemplate)

    async def list_available_to(
        self, user_id: uuid.UUID, is_admin: bool, pagination: PaginationParams
    ) -> tuple[Sequence[CertificateTemplate], int]:
        stmt = self._base_select()
        if not is_admin:
            stmt = stmt.where(or_(CertificateTemplate.owner_id == user_id, CertificateTemplate.owner_id.is_(None)))
        stmt = stmt.order_by(CertificateTemplate.created_at.desc())
        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total

    async def get_first_global_template(self) -> CertificateTemplate | None:
        stmt = (
            self._base_select()
            .where(CertificateTemplate.owner_id.is_(None), CertificateTemplate.is_active.is_(True))
            .order_by(CertificateTemplate.created_at.asc())
        )
        return (await self.session.execute(stmt)).scalars().first()


class CertificateRepository(BaseRepository[Certificate]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Certificate)

    async def get_for_user_course(self, user_id: uuid.UUID, course_id: uuid.UUID) -> Certificate | None:
        stmt = self._base_select().where(Certificate.user_id == user_id, Certificate.course_id == course_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_verification_code(self, code: str) -> Certificate | None:
        stmt = self._base_select().where(Certificate.verification_code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(
        self, user_id: uuid.UUID, pagination: PaginationParams
    ) -> tuple[Sequence[Certificate], int]:
        stmt = self._base_select().where(Certificate.user_id == user_id).order_by(Certificate.issued_at.desc())
        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total

    async def exists_certificate_number(self, certificate_number: str) -> bool:
        stmt = select(Certificate.id).where(Certificate.certificate_number == certificate_number)
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def list_pending_scheduled_completions(self, now: datetime) -> Sequence[tuple[User, Course]]:
        """Every (user, course) pair where the student has completed a SCHEDULED
        course whose access_end_date has now passed, but no certificate has been
        issued yet - i.e. the backlog `CertificateService.ensure_issued` withheld
        at completion time because the course's deadline hadn't closed yet."""
        stmt = (
            select(User, Course)
            .select_from(UserCourseProgress)
            .join(Course, Course.id == UserCourseProgress.course_id)
            .join(User, User.id == UserCourseProgress.user_id)
            .outerjoin(
                Certificate,
                (Certificate.user_id == UserCourseProgress.user_id)
                & (Certificate.course_id == UserCourseProgress.course_id),
            )
            .where(
                UserCourseProgress.is_completed.is_(True),
                Course.access_mode == CourseAccessModeEnum.SCHEDULED,
                Course.certificate_enabled.is_(True),
                Course.access_end_date.is_not(None),
                Course.access_end_date <= now,
                Course.deleted_at.is_(None),
                Certificate.id.is_(None),
            )
        )
        return (await self.session.execute(stmt)).all()
