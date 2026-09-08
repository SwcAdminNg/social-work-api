import uuid
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_repository import BaseRepository
from app.common.pagination import PaginationParams
from app.modules.notification.entity import Notification


class NotificationRepository(BaseRepository[Notification]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Notification)

    async def list_for_user(
        self, user_id: uuid.UUID, pagination: PaginationParams, unread_only: bool = False
    ) -> tuple[Sequence[Notification], int]:
        stmt = self._base_select().where(Notification.user_id == user_id)
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))
        stmt = stmt.order_by(Notification.created_at.desc())

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total

    async def count_unread(self, user_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(
            self._base_select().where(Notification.user_id == user_id, Notification.is_read.is_(False)).subquery()
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def get_for_user(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> Notification | None:
        stmt = self._base_select().where(Notification.id == notification_id, Notification.user_id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def mark_read(self, notification: Notification) -> Notification:
        notification.is_read = True
        notification.read_at = datetime.now(timezone.utc)
        await self.session.flush()
        return notification

    async def mark_all_read(self, user_id: uuid.UUID) -> None:
        stmt = (
            update(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
            .values(is_read=True, read_at=datetime.now(timezone.utc))
        )
        await self.session.execute(stmt)
