import uuid
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_repository import BaseRepository
from app.common.pagination import PaginationParams
from app.modules.coupon.entity import Coupon, CouponRedemption


class CouponRepository(BaseRepository[Coupon]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Coupon)

    async def get_by_code(self, code: str) -> Coupon | None:
        stmt = self._base_select().where(Coupon.code == code.strip().upper())
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def exists_code(self, code: str) -> bool:
        stmt = select(Coupon.id).where(Coupon.code == code.strip().upper())
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def list_all(self, pagination: PaginationParams) -> tuple[Sequence[Coupon], int]:
        stmt = self._base_select().order_by(Coupon.created_at.desc())
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total

    async def count_user_redemptions(self, coupon_id: uuid.UUID, user_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(CouponRedemption).where(
            CouponRedemption.coupon_id == coupon_id, CouponRedemption.user_id == user_id
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def record_redemption(
        self, coupon: Coupon, user_id: uuid.UUID, transaction_id: uuid.UUID, discount_amount: float
    ) -> CouponRedemption:
        redemption = CouponRedemption(
            coupon_id=coupon.id, user_id=user_id, transaction_id=transaction_id, discount_amount=discount_amount
        )
        self.session.add(redemption)
        coupon.times_redeemed += 1
        await self.session.flush()
        return redemption
