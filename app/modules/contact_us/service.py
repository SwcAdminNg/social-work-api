import uuid
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.modules.contact_us.dto import ContactUsCreateDTO, ContactUsFilterParams
from app.modules.contact_us.entity import ContactUsMessage
from app.modules.contact_us.repository import ContactUsRepository


class ContactUsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ContactUsRepository(session)

    async def submit(self, payload: ContactUsCreateDTO) -> ContactUsMessage:
        message = ContactUsMessage(**payload.model_dump())
        await self.repository.create(message)
        await self.session.commit()
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
