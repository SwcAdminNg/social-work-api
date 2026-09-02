import uuid
from typing import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_repository import BaseRepository
from app.modules.cart.entity import CartItem


class CartRepository(BaseRepository[CartItem]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CartItem)

    async def list_for_user(self, user_id: uuid.UUID) -> Sequence[CartItem]:
        stmt = self._base_select().where(CartItem.user_id == user_id).order_by(CartItem.created_at.asc())
        return (await self.session.execute(stmt)).scalars().all()

    async def get_item(self, user_id: uuid.UUID, course_id: uuid.UUID) -> CartItem | None:
        stmt = self._base_select().where(CartItem.user_id == user_id, CartItem.course_id == course_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def remove_item(self, user_id: uuid.UUID, course_id: uuid.UUID) -> bool:
        item = await self.get_item(user_id, course_id)
        if not item:
            return False
        await self.session.delete(item)
        await self.session.flush()
        return True

    async def clear(self, user_id: uuid.UUID) -> None:
        await self.session.execute(delete(CartItem).where(CartItem.user_id == user_id))
        await self.session.flush()
