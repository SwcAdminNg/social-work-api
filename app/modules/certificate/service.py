import secrets
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.core.config import settings
from app.core.storage import get_r2_client
from app.modules.certificate.dto import (
    CertificateImageUploadRequestDTO,
    CertificateImageUploadResponseDTO,
    CertificateReadDTO,
    CertificateTemplateCreateDTO,
    CertificateTemplateUpdateDTO,
    CourseCertificateSettingsUpdateDTO,
    PublicCertificateVerifyDTO,
)
from app.modules.certificate.entity import Certificate, CertificateTemplate
from app.modules.certificate.renderer import render_certificate_pdf
from app.modules.certificate.repository import CertificateRepository, CertificateTemplateRepository
from app.modules.course.entity import Course, CourseAccessModeEnum
from app.modules.course.repository import CourseRepository
from app.modules.user.entity import User, UserTypeEnum


class CertificateTemplateService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CertificateTemplateRepository(session)

    def _ensure_can_manage(self, template: CertificateTemplate, user: User) -> None:
        if user.user_type == UserTypeEnum.ADMIN:
            return
        if template.owner_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not manage this certificate template")

    async def create(self, payload: CertificateTemplateCreateDTO, current_user: User) -> CertificateTemplate:
        # Admins may create global templates (owner_id=None, visible to every
        # instructor); instructors always own the templates they create.
        owner_id = None if current_user.user_type == UserTypeEnum.ADMIN else current_user.id
        template = CertificateTemplate(owner_id=owner_id, **payload.model_dump())
        await self.repo.create(template)
        await self.session.commit()
        return template

    async def get_for_manage(self, template_id: uuid.UUID, current_user: User) -> CertificateTemplate:
        template = await self.repo.get_by_id(template_id)
        if template is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Certificate template not found")
        self._ensure_can_manage(template, current_user)
        return template

    async def list_available(
        self, pagination: PaginationParams, current_user: User
    ) -> tuple[list[CertificateTemplate], int]:
        return await self.repo.list_available_to(
            current_user.id, current_user.user_type == UserTypeEnum.ADMIN, pagination
        )

    async def update(
        self, template_id: uuid.UUID, payload: CertificateTemplateUpdateDTO, current_user: User
    ) -> CertificateTemplate:
        template = await self.get_for_manage(template_id, current_user)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(template, field, value)
        await self.repo.update(template)
        await self.session.commit()
        return template

    async def delete(self, template_id: uuid.UUID, current_user: User) -> None:
        template = await self.get_for_manage(template_id, current_user)
        await self.repo.soft_delete(template, current_user.id)
        await self.session.commit()

    async def generate_image_upload_url(
        self, template_id: uuid.UUID, field: str, payload: CertificateImageUploadRequestDTO, current_user: User
    ) -> CertificateImageUploadResponseDTO:
        """`field` is either "logo" or "signature" - both are small branding
        images uploaded directly to R2 and stored as a public URL, same pattern
        as `Course.thumbnail_url`."""
        template = await self.get_for_manage(template_id, current_user)
        r2_client = get_r2_client()
        key = r2_client.build_certificate_template_image_key(template.id, payload.file_name)
        upload_url = r2_client.generate_upload_url(key, payload.content_type)
        public_url = r2_client.get_public_url(key)

        if field == "logo":
            template.logo_url = public_url
        else:
            template.signature_image_url = public_url
        await self.repo.update(template)
        await self.session.commit()

        return CertificateImageUploadResponseDTO(upload_url=upload_url, image_url=public_url)


class CertificateService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CertificateRepository(session)
        self.template_repo = CertificateTemplateRepository(session)
        self.course_repo = CourseRepository(session)

    # -- course <-> template assignment --------------------------------------

    async def update_course_certificate_settings(
        self, course_id: uuid.UUID, payload: CourseCertificateSettingsUpdateDTO, current_user: User
    ) -> Course:
        from app.modules.course.service import CourseService

        course = await CourseService(self.session).get_for_manage(course_id, current_user)

        if payload.clear_template:
            course.certificate_template_id = None
        elif payload.certificate_template_id is not None:
            template = await self.template_repo.get_by_id(payload.certificate_template_id)
            if template is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Certificate template not found")
            if (
                current_user.user_type != UserTypeEnum.ADMIN
                and template.owner_id is not None
                and template.owner_id != current_user.id
            ):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot use another instructor's template")
            course.certificate_template_id = template.id

        if payload.certificate_enabled is not None:
            course.certificate_enabled = payload.certificate_enabled

        await self.course_repo.update(course)
        await self.session.commit()
        return course

    async def _resolve_template(self, course: Course) -> CertificateTemplate | None:
        if course.certificate_template_id is not None:
            template = await self.template_repo.get_by_id(course.certificate_template_id)
            if template is not None and template.is_active:
                return template
        return await self.template_repo.get_first_global_template()

    # -- issuance --------------------------------------------------------------

    @staticmethod
    def _generate_certificate_number(issued_at: datetime) -> str:
        return f"SW-{issued_at:%Y}-{secrets.token_hex(4).upper()}"

    @staticmethod
    def _is_awaiting_scheduled_deadline(course: Course) -> bool:
        """A SCHEDULED course (one with a configured access_start_date/
        access_end_date "term") withholds certificates until its scheduled
        window actually closes, even for a student who finishes every item
        early - mirrors a cohort course where everyone is certified together at
        the course's official end date, not the moment they personally finish.
        A SELF_PACED course (or a SCHEDULED one with no end date set) has no
        such deadline and issues immediately, as before."""
        if course.access_mode != CourseAccessModeEnum.SCHEDULED or course.access_end_date is None:
            return False
        return datetime.now(timezone.utc) < course.access_end_date

    async def ensure_issued(self, user: User, course: Course) -> Certificate | None:
        """Idempotently issues a certificate the moment a course is completed.
        Called from `LearningService._recalculate_progress`, and again by
        `process_scheduled_course_certificates` (the daily cron sweep) once a
        SCHEDULED course's deadline actually passes. Returns None (no-op) when
        certificates are disabled for the course, the course's scheduled window
        hasn't closed yet (see `_is_awaiting_scheduled_deadline`), or no template
        is configured/available - completion itself is unaffected either way."""
        if not course.certificate_enabled:
            return None
        if self._is_awaiting_scheduled_deadline(course):
            return None

        existing = await self.repo.get_for_user_course(user.id, course.id)
        if existing is not None:
            return existing

        template = await self._resolve_template(course)
        if template is None:
            return None

        issued_at = datetime.now(timezone.utc)
        certificate_number = self._generate_certificate_number(issued_at)
        while await self.repo.exists_certificate_number(certificate_number):
            certificate_number = self._generate_certificate_number(issued_at)

        certificate = Certificate(
            user_id=user.id,
            course_id=course.id,
            template_id=template.id,
            certificate_number=certificate_number,
            verification_code=secrets.token_urlsafe(16),
            issued_at=issued_at,
            recipient_name=f"{user.first_name} {user.last_name}".strip(),
            course_title=course.title,
        )
        await self.repo.create(certificate)
        await self.session.commit()
        return certificate

    async def process_scheduled_course_certificates(self) -> dict:
        """Daily cron sweep (see `/certificates/cron/process-scheduled-certificates`)
        that catches students who completed a SCHEDULED course *before* its
        access_end_date - `ensure_issued` withholds their certificate at
        completion time (`_is_awaiting_scheduled_deadline`), so nothing else
        ever revisits them once they've stopped interacting with the course.
        This finds every such course whose deadline has now passed and issues
        the backlog in one pass."""
        now = datetime.now(timezone.utc)
        pending = await self.repo.list_pending_scheduled_completions(now)
        issued = 0
        for user, course in pending:
            certificate = await self.ensure_issued(user, course)
            if certificate is not None:
                issued += 1
        return {"checked": len(pending), "issued": issued}

    # -- rendering / delivery ---------------------------------------------------

    def _verify_url(self, verification_code: str) -> str:
        return f"{settings.frontend_url.rstrip('/')}/certificates/verify/{verification_code}"

    async def _render_and_cache(self, certificate: Certificate, instructor_name: str) -> str:
        template = None
        if certificate.template_id is not None:
            template = await self.template_repo.get_by_id(certificate.template_id)
        if template is None:
            template = await self.template_repo.get_first_global_template()
        if template is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No certificate template available to render this certificate")

        pdf_bytes = render_certificate_pdf(
            template=template,
            recipient_name=certificate.recipient_name,
            course_title=certificate.course_title,
            completion_date_str=certificate.issued_at.strftime("%B %d, %Y"),
            instructor_name=instructor_name,
            certificate_number=certificate.certificate_number,
            verification_code=certificate.verification_code,
            verify_url=self._verify_url(certificate.verification_code),
        )

        r2_client = get_r2_client()
        key = r2_client.build_certificate_pdf_key(certificate.course_id, certificate.user_id, certificate.id)
        r2_client.upload_bytes(key, pdf_bytes, "application/pdf")
        public_url = r2_client.get_public_url(key)

        certificate.pdf_url = public_url
        await self.repo.update(certificate)
        await self.session.commit()
        return public_url

    async def get_my_certificate(self, user: User, course_id: uuid.UUID) -> CertificateReadDTO:
        certificate = await self.repo.get_for_user_course(user.id, course_id)
        if certificate is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "No certificate has been issued for this course yet - complete the course to earn one",
            )
        return await self._build_read_dto(certificate)

    async def _build_read_dto(self, certificate: Certificate) -> CertificateReadDTO:
        pdf_url = certificate.pdf_url
        if pdf_url is None:
            course = await self.course_repo.get_by_id(certificate.course_id)
            from app.modules.user.repository import UserRepository

            instructor = await UserRepository(self.session).get_by_id(course.instructor_id) if course else None
            instructor_name = f"{instructor.first_name} {instructor.last_name}".strip() if instructor else ""
            pdf_url = await self._render_and_cache(certificate, instructor_name)

        return CertificateReadDTO(
            id=certificate.id,
            course_id=certificate.course_id,
            course_title=certificate.course_title,
            recipient_name=certificate.recipient_name,
            certificate_number=certificate.certificate_number,
            verification_code=certificate.verification_code,
            issued_at=certificate.issued_at,
            pdf_url=pdf_url,
            verify_url=self._verify_url(certificate.verification_code),
        )

    async def list_my_certificates(
        self, user: User, pagination: PaginationParams
    ) -> tuple[list[CertificateReadDTO], int]:
        items, total = await self.repo.list_for_user(user.id, pagination)
        return [await self._build_read_dto(c) for c in items], total

    async def verify(self, verification_code: str) -> PublicCertificateVerifyDTO:
        certificate = await self.repo.get_by_verification_code(verification_code)
        if certificate is None:
            return PublicCertificateVerifyDTO(valid=False)

        pdf_url = certificate.pdf_url
        if pdf_url is None:
            dto = await self._build_read_dto(certificate)
            pdf_url = dto.pdf_url

        return PublicCertificateVerifyDTO(
            valid=True,
            recipient_name=certificate.recipient_name,
            course_title=certificate.course_title,
            certificate_number=certificate.certificate_number,
            issued_at=certificate.issued_at,
            pdf_url=pdf_url,
        )
