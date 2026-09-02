import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.modules.coupon.dto import CouponCreateDTO, CouponUpdateDTO
from app.modules.coupon.entity import Coupon, CouponDiscountTypeEnum
from app.modules.coupon.repository import CouponRepository
from app.modules.course.entity import Course
from app.modules.user.entity import User


@dataclass
class PricedLine:
    course_id: uuid.UUID
    price: float
    category: object  # CourseCategoryEnum


@dataclass
class CouponApplication:
    coupon: Coupon
    subtotal_amount: float
    discount_amount: float
    total_amount: float


class CouponService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = CouponRepository(session)

    # -- admin CRUD -----------------------------------------------------------

    async def create(self, payload: CouponCreateDTO) -> Coupon:
        if await self.repo.exists_code(payload.code):
            raise HTTPException(status.HTTP_409_CONFLICT, "A coupon with this code already exists")
        coupon = Coupon(**payload.model_dump())
        await self.repo.create(coupon)
        await self.session.commit()
        return coupon

    async def list_all(self, pagination: PaginationParams):
        return await self.repo.list_all(pagination)

    async def get_by_id(self, coupon_id: uuid.UUID) -> Coupon:
        coupon = await self.repo.get_by_id(coupon_id)
        if not coupon:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Coupon not found")
        return coupon

    async def update(self, coupon_id: uuid.UUID, payload: CouponUpdateDTO) -> Coupon:
        coupon = await self.get_by_id(coupon_id)
        updates = payload.model_dump(exclude_unset=True)
        if "code" in updates and updates["code"] != coupon.code and await self.repo.exists_code(updates["code"]):
            raise HTTPException(status.HTTP_409_CONFLICT, "A coupon with this code already exists")
        for field, value in updates.items():
            setattr(coupon, field, value)
        await self.repo.update(coupon)
        await self.session.commit()
        return coupon

    async def delete(self, coupon_id: uuid.UUID) -> None:
        coupon = await self.get_by_id(coupon_id)
        await self.repo.soft_delete(coupon)
        await self.session.commit()

    # -- discount engine, shared by single-course and cart checkout -----------

    def _course_qualifies(self, coupon: Coupon, line: PricedLine) -> bool:
        if coupon.applicable_course_ids is None and coupon.applicable_category is None:
            return True
        if coupon.applicable_course_ids and line.course_id in coupon.applicable_course_ids:
            return True
        if coupon.applicable_category and line.category == coupon.applicable_category:
            return True
        return False

    async def validate_and_compute(
        self, code: str, user: User, courses: list[Course]
    ) -> CouponApplication:
        coupon = await self.repo.get_by_code(code)
        if not coupon:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid coupon code")
        if not coupon.is_active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This coupon is no longer active")

        now = datetime.now(timezone.utc)
        if coupon.valid_from and now < coupon.valid_from:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This coupon is not active yet")
        if coupon.valid_until and now > coupon.valid_until:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This coupon has expired")

        if coupon.max_redemptions is not None and coupon.times_redeemed >= coupon.max_redemptions:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This coupon has reached its redemption limit")

        user_redemptions = await self.repo.count_user_redemptions(coupon.id, user.id)
        if user_redemptions >= coupon.max_redemptions_per_user:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "You've already used this coupon")

        if coupon.new_users_only and await self._has_previous_purchase(user.id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This coupon is only valid for first-time buyers")

        subtotal_amount = sum(float(course.price) for course in courses)
        if coupon.min_order_amount is not None and subtotal_amount < float(coupon.min_order_amount):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"This coupon requires a minimum order of ₦{float(coupon.min_order_amount):,.2f}",
            )

        lines = [PricedLine(course_id=c.id, price=float(c.price), category=c.category) for c in courses]
        eligible_amount = sum(line.price for line in lines if self._course_qualifies(coupon, line))
        if eligible_amount <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This coupon does not apply to any items in your order")

        if coupon.discount_type == CouponDiscountTypeEnum.PERCENTAGE:
            discount_amount = eligible_amount * (float(coupon.discount_value) / 100)
            if coupon.max_discount_amount is not None:
                discount_amount = min(discount_amount, float(coupon.max_discount_amount))
        else:
            discount_amount = min(float(coupon.discount_value), eligible_amount)

        discount_amount = round(discount_amount, 2)
        total_amount = round(subtotal_amount - discount_amount, 2)
        if total_amount <= 0:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "This coupon would reduce your total to zero - it can't be applied"
            )

        return CouponApplication(
            coupon=coupon, subtotal_amount=subtotal_amount, discount_amount=discount_amount, total_amount=total_amount
        )

    async def _has_previous_purchase(self, user_id: uuid.UUID) -> bool:
        from sqlalchemy import select

        from app.modules.payment.entity import Transaction, TransactionStatusEnum

        stmt = select(Transaction.id).where(
            Transaction.user_id == user_id, Transaction.status == TransactionStatusEnum.SUCCESS
        ).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def redeem(self, coupon: Coupon, user_id: uuid.UUID, transaction_id: uuid.UUID, discount_amount: float) -> None:
        await self.repo.record_redemption(coupon, user_id, transaction_id, discount_amount)
