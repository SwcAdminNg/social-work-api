import uuid
from datetime import datetime, time, timedelta
from typing import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_repository import BaseRepository
from app.common.pagination import PaginationParams
from app.modules.support.dto import SupportTicketFilterParams
from app.modules.support.entity import (
    FAQCategory,
    FAQItem,
    SupportMessage,
    SupportTicket,
    SupportTicketStatusEnum,
)
from app.modules.user.entity import User


class FAQCategoryRepository(BaseRepository[FAQCategory]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, FAQCategory)

    async def list_ordered(self) -> Sequence[FAQCategory]:
        stmt = self._base_select().order_by(FAQCategory.order.asc(), FAQCategory.created_at.asc())
        return (await self.session.execute(stmt)).scalars().all()


class FAQItemRepository(BaseRepository[FAQItem]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, FAQItem)

    async def list_published(self) -> Sequence[FAQItem]:
        stmt = (
            self._base_select()
            .where(FAQItem.is_published.is_(True))
            .order_by(FAQItem.order.asc(), FAQItem.created_at.asc())
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def list_all_for_admin(self, pagination: PaginationParams) -> tuple[Sequence[FAQItem], int]:
        stmt = self._base_select().order_by(FAQItem.order.asc(), FAQItem.created_at.asc())
        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total


class SupportTicketRepository(BaseRepository[SupportTicket]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SupportTicket)

    async def list_for_user(
        self, user_id: uuid.UUID, pagination: PaginationParams
    ) -> tuple[Sequence[SupportTicket], int]:
        stmt = self._base_select().where(SupportTicket.user_id == user_id).order_by(SupportTicket.created_at.desc())
        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total

    async def list_for_admin(
        self,
        pagination: PaginationParams,
        filters: SupportTicketFilterParams | None = None,
    ) -> tuple[Sequence[SupportTicket], int]:
        stmt = self._base_select()

        if filters is not None:
            if filters.status is not None:
                stmt = stmt.where(SupportTicket.status == filters.status)
            if filters.assigned_admin_id is not None:
                stmt = stmt.where(SupportTicket.assigned_admin_id == filters.assigned_admin_id)
            if filters.search is not None:
                term = f"%{filters.search}%"
                stmt = stmt.join(User, SupportTicket.user_id == User.id).where(
                    or_(
                        SupportTicket.subject.ilike(term),
                        User.username.ilike(term),
                        User.first_name.ilike(term),
                        User.last_name.ilike(term),
                        func.concat(User.first_name, " ", User.last_name).ilike(term),
                        User.email.ilike(term),
                        User.phone_number.ilike(term),
                    )
                )
            if filters.start_date is not None:
                stmt = stmt.where(
                    SupportTicket.created_at >= datetime.combine(filters.start_date, time.min)
                )
            if filters.end_date is not None:
                stmt = stmt.where(
                    SupportTicket.created_at
                    < datetime.combine(filters.end_date, time.min) + timedelta(days=1)
                )

        stmt = stmt.order_by(SupportTicket.created_at.desc())

        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total

    async def get_open_or_in_progress_for_user(self, user_id: uuid.UUID) -> SupportTicket | None:
        stmt = self._base_select().where(
            SupportTicket.user_id == user_id,
            SupportTicket.status.in_([SupportTicketStatusEnum.OPEN, SupportTicketStatusEnum.IN_PROGRESS]),
        )
        return (await self.session.execute(stmt)).scalars().first()


class SupportMessageRepository(BaseRepository[SupportMessage]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SupportMessage)

    async def list_for_ticket(
        self, ticket_id: uuid.UUID, pagination: PaginationParams
    ) -> tuple[Sequence[SupportMessage], int]:
        stmt = (
            self._base_select()
            .where(SupportMessage.ticket_id == ticket_id)
            .order_by(SupportMessage.created_at.asc())
        )
        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total
