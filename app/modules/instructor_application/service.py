import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.core.config import settings
from app.core.email import email_service
from app.core.security import (
    create_interim_token,
    generate_opaque_token,
    hash_password,
    hash_token,
)
from app.core.storage import get_r2_client
from app.modules.auth.dto import LoginResponseDTO, TwoFactorChallengeDTO
from app.modules.auth.entity import InstructorSetupToken
from app.modules.auth.repository import InstructorSetupTokenRepository
from app.modules.auth.service import TWO_FACTOR_SETUP_TOKEN_TYPE
from app.modules.instructor_application.dto import (
    ApproveInstructorApplicationRequestDTO,
    CompleteInstructorSetupRequestDTO,
    InstructorApplicationDetailDTO,
    InstructorApplicationReadDTO,
    InstructorApplicationUploadResponseDTO,
    RejectInstructorApplicationRequestDTO,
    SubmitInstructorApplicationRequestDTO,
)
from app.modules.instructor_application.entity import InstructorApplication, InstructorApplicationStatusEnum
from app.modules.instructor_application.repository import InstructorApplicationRepository
from app.modules.notification.service import NotificationService
from app.modules.user.entity import User, UserTypeEnum
from app.modules.user.repository import UserRepository

logger = logging.getLogger(__name__)


class InstructorApplicationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.applications = InstructorApplicationRepository(session)
        self.users = UserRepository(session)
        self.setup_tokens = InstructorSetupTokenRepository(session)
        self.r2 = get_r2_client()

    # -- public: application intake -------------------------------------------------

    async def submit_application(
        self, payload: SubmitInstructorApplicationRequestDTO
    ) -> InstructorApplicationUploadResponseDTO:
        if await self.users.email_exists(payload.email):
            raise HTTPException(status.HTTP_409_CONFLICT, "This email is already registered")
        if await self.applications.has_pending_for_email(payload.email):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "An application from this email is already under review"
            )

        application = InstructorApplication(
            first_name=payload.first_name,
            last_name=payload.last_name,
            email=payload.email.lower(),
            phone_number=payload.phone_number,
            cv_file_name=payload.cv_file_name,
            cv_storage_key="",
        )
        await self.applications.create(application)

        storage_key = self.r2.build_instructor_cv_key(application.id, payload.cv_file_name)
        application.cv_storage_key = storage_key
        await self.session.commit()

        try:
            await NotificationService(self.session).notify_admins_new_instructor_application(
                application.id, application.first_name, application.last_name, application.email
            )
        except Exception as e:
            logger.error(f"Failed to notify admins of new instructor application {application.id}: {e}")

        return InstructorApplicationUploadResponseDTO(
            application_id=application.id,
            upload_url=self.r2.generate_upload_url(storage_key, payload.cv_content_type),
            storage_key=storage_key,
        )

    # -- admin: review ----------------------------------------------------------------

    async def list_applications(
        self, pagination: PaginationParams, application_status: InstructorApplicationStatusEnum | None
    ):
        return await self.applications.list_by_status(pagination, application_status)

    async def get_application_detail(self, application_id: uuid.UUID) -> InstructorApplicationDetailDTO:
        application = await self._get_or_404(application_id)
        return InstructorApplicationDetailDTO(
            **InstructorApplicationReadDTO.model_validate(application, from_attributes=True).model_dump(),
            cv_download_url=self.r2.generate_download_url(application.cv_storage_key),
        )

    async def approve(
        self, application_id: uuid.UUID, admin: User, payload: ApproveInstructorApplicationRequestDTO
    ) -> InstructorApplication:
        application = await self._get_or_404(application_id)
        if application.status != InstructorApplicationStatusEnum.PENDING:
            raise HTTPException(status.HTTP_409_CONFLICT, "This application has already been reviewed")

        username = await self._generate_placeholder_username()
        user = User(
            first_name=application.first_name,
            last_name=application.last_name,
            email=application.email,
            username=username,
            phone_number=application.phone_number,
            platform=payload.platform,
            user_type=UserTypeEnum.INSTRUCTOR,
            hashed_password=None,
            is_active=False,
            created_by=admin.id,
        )
        await self.users.create(user)

        application.status = InstructorApplicationStatusEnum.APPROVED
        application.reviewed_by = admin.id
        application.reviewed_at = datetime.now(timezone.utc)
        application.user_id = user.id
        await self.applications.update(application)
        await self.session.commit()

        await self._issue_and_send_setup_link(user)

        return application

    async def reject(
        self, application_id: uuid.UUID, admin: User, payload: RejectInstructorApplicationRequestDTO
    ) -> InstructorApplication:
        application = await self._get_or_404(application_id)
        if application.status != InstructorApplicationStatusEnum.PENDING:
            raise HTTPException(status.HTTP_409_CONFLICT, "This application has already been reviewed")

        application.status = InstructorApplicationStatusEnum.REJECTED
        application.rejection_reason = payload.reason
        application.reviewed_by = admin.id
        application.reviewed_at = datetime.now(timezone.utc)
        await self.applications.update(application)
        await self.session.commit()

        try:
            await email_service.send_instructor_application_rejected_email(
                application.email, application.first_name, payload.reason
            )
        except Exception as e:
            logger.error(f"Failed to send rejection email for application {application.id}: {e}")

        return application

    async def resend_setup_link(self, application_id: uuid.UUID, admin: User) -> None:
        application = await self._get_or_404(application_id)
        if application.status != InstructorApplicationStatusEnum.APPROVED or application.user_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This application has not been approved")

        user = await self.users.get_by_id(application.user_id)
        if user is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "The instructor account for this application no longer exists")
        if user.hashed_password is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This instructor has already completed account setup")

        await self.setup_tokens.invalidate_all_for_user(user.id)
        await self.session.commit()
        await self._issue_and_send_setup_link(user)

    # -- public: setup completion ------------------------------------------------------

    async def complete_setup(self, payload: CompleteInstructorSetupRequestDTO) -> LoginResponseDTO:
        token_hash = hash_token(payload.token)
        stored_token = await self.setup_tokens.get_valid_by_hash(token_hash)

        if stored_token is None or stored_token.expires_at < datetime.now(timezone.utc):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired setup link")

        user = await self.users.get_by_id(stored_token.user_id)
        if user is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired setup link")

        if await self.users.username_exists(payload.username):
            raise HTTPException(status.HTTP_409_CONFLICT, "Username is already taken")

        user.username = payload.username
        user.hashed_password = await hash_password(payload.password)
        user.is_active = True
        await self.setup_tokens.mark_used(stored_token)
        await self.session.commit()

        challenge_token = create_interim_token(
            subject=str(user.id),
            token_type=TWO_FACTOR_SETUP_TOKEN_TYPE,
            expire_minutes=settings.two_factor_challenge_expire_minutes,
        )
        return LoginResponseDTO(
            status="two_factor_setup_required",
            challenge=TwoFactorChallengeDTO(challenge_token=challenge_token),
        )

    # -- internals -----------------------------------------------------------------

    async def _get_or_404(self, application_id: uuid.UUID) -> InstructorApplication:
        application = await self.applications.get_by_id(application_id)
        if application is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Instructor application not found")
        return application

    async def _generate_placeholder_username(self) -> str:
        for _ in range(10):
            candidate = f"instructor_{secrets.token_hex(4)}"
            if not await self.users.username_exists(candidate):
                return candidate
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not allocate a username, please retry")

    async def _issue_and_send_setup_link(self, user: User) -> None:
        raw_token = generate_opaque_token()
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.instructor_setup_token_expire_minutes
        )
        setup_token = InstructorSetupToken(user_id=user.id, token_hash=hash_token(raw_token), expires_at=expires_at)
        await self.setup_tokens.create(setup_token)
        await self.session.commit()

        setup_link = f"{settings.frontend_url.rstrip('/')}/instructor/complete-setup?token={raw_token}"
        try:
            await email_service.send_instructor_application_approved_email(user.email, user.first_name, setup_link)
        except Exception as e:
            logger.error(f"Failed to send instructor setup email to {user.email}: {e}")
