from datetime import datetime, time, timedelta
from typing import Sequence

from sqlalchemy import String, cast, func, or_, select
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
            if filters.source_page is not None:
                stmt = stmt.where(ContactUsMessage.source_page == filters.source_page)
            if filters.search is not None:
                search = filters.search.strip()
                term = f"%{search}%"
                conditions = [
                    ContactUsMessage.full_name.ilike(term),
                    ContactUsMessage.email.ilike(term),
                    ContactUsMessage.phone_number.ilike(term),
                ]
                # A reference such as "SWCL-1A2B3C4D" is the start of the message id.
                ref = search.upper().removeprefix("SWCL-").replace("-", "")
                if 4 <= len(ref) <= 32 and all(c in "0123456789ABCDEF" for c in ref):
                    conditions.append(
                        func.replace(cast(ContactUsMessage.id, String), "-", "").ilike(f"{ref.lower()}%")
                    )
                stmt = stmt.where(or_(*conditions))
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
