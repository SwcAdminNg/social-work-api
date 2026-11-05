import logging
import uuid
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.core.config import settings
from app.core.email import EmailService
from app.modules.contact_us.dto import ContactUsCreateDTO, ContactUsFilterParams, ContactUsReadDTO
from app.modules.contact_us.entity import ContactUsMessage
from app.modules.contact_us.repository import ContactUsRepository
from app.modules.notification.service import NotificationService

logger = logging.getLogger(__name__)


class ContactUsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ContactUsRepository(session)

    async def submit(self, payload: ContactUsCreateDTO) -> ContactUsMessage:
        message = ContactUsMessage(**payload.model_dump())
        await self.repository.create(message)
        await self.session.commit()
        await NotificationService(self.session).notify_admins_new_contact_message(
            message.full_name, message.id, message.source_page
        )
        return message

    async def list(
        self, pagination: PaginationParams, filters: ContactUsFilterParams | None = None
    ) -> tuple[Sequence[ContactUsMessage], int]:
        return await self.repository.list(pagination, filters)

    async def get_by_id(self, id: uuid.UUID) -> ContactUsMessage:
        message = await self.repository.get_by_id(id)
        if message is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact us message not found")
        return message


async def send_enquiry_notification(message: ContactUsReadDTO) -> None:
    """Emails the enquiry to the configured mailbox. Runs after the response is
    sent; the enquiry is already stored, so a failed email is logged rather than
    lost, and the message stays visible in the admin."""
    try:
        await EmailService().send_contact_enquiry_email(
            settings.contact_notify_email,
            reference=message.reference,
            category_label=message.category_label or "General",
            full_name=message.full_name,
            email=message.email,
            phone_number=message.phone_number,
            source_page=message.source_page,
            message=message.message,
        )
    except Exception:  # noqa: BLE001 - never let a mail failure surface to the visitor
        logger.exception("Failed to email contact enquiry %s", message.reference)
