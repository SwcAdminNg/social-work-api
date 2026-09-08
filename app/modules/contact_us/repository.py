from datetime import datetime, time, timedelta
from typing import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_repository import BaseRepository
from app.common.pagination import PaginationParams
from app.modules.contact_us.dto import ContactUsFilterParams
from app.modules.contact_us.entity import ContactUsMessage


class ContactUsRepository(BaseRepository[ContactUsMessage]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ContactUsMessage)

    async def list(
        self, pagination: PaginationParams, filters: ContactUsFilterParams | None = None
    ) -> tuple[Sequence[ContactUsMessage], int]:
        stmt = self._base_select()

        if filters is not None:
            if filters.platform is not None:
                stmt = stmt.where(ContactUsMessage.platform == filters.platform)
            if filters.category is not None:
                stmt = stmt.where(ContactUsMessage.category == filters.category)
            if filters.search is not None:
                term = f"%{filters.search}%"
                stmt = stmt.where(
                    or_(
                        ContactUsMessage.full_name.ilike(term),
                        ContactUsMessage.email.ilike(term),
                        ContactUsMessage.phone_number.ilike(term),
                    )
                )
            if filters.start_date is not None:
                stmt = stmt.where(
                    ContactUsMessage.created_at >= datetime.combine(filters.start_date, time.min)
                )
            if filters.end_date is not None:
                stmt = stmt.where(
                    ContactUsMessage.created_at
                    < datetime.combine(filters.end_date, time.min) + timedelta(days=1)
                )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total

    async def count_total(self) -> int:
        stmt = select(func.count()).select_from(self._base_select().subquery())
        return (await self.session.execute(stmt)).scalar_one()

    async def count_since(self, since: datetime) -> int:
        """There's no read/unread status on a contact-us message - this counts
        messages received since `since` (e.g. the last 7 days) as the closest
        proxy for "recent, may need a look", not a true unread count."""
        stmt = select(func.count()).select_from(
            self._base_select().where(ContactUsMessage.created_at >= since).subquery()
        )
        return (await self.session.execute(stmt)).scalar_one()
