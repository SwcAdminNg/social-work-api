import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity
from app.modules.course.entity import CourseCategoryEnum


class CouponDiscountTypeEnum(str, enum.Enum):
    PERCENTAGE = "PERCENTAGE"
    FIXED_AMOUNT = "FIXED_AMOUNT"


class Coupon(BaseEntity):
    """An admin-managed discount code. Redemption counters (`times_redeemed`) are
    only ever incremented on a *successful* payment (see `CouponService.redeem`,
    called from `PaymentService._grant_access`) - abandoned/failed checkouts never
    consume a redemption slot.

    `applicable_course_ids`/`applicable_category` scope which cart items the
    discount can apply to; when both are null the coupon applies to every
    course. In a mixed cart, only the qualifying items' subtotal is discounted
    (see `CouponService.validate_and_compute`) rather than rejecting the whole
    order."""

    __tablename__ = "coupons"

    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    discount_type: Mapped[CouponDiscountTypeEnum] = mapped_column(
        Enum(CouponDiscountTypeEnum, name="coupon_discount_type_enum", native_enum=True), nullable=False
    )
    discount_value: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    # Caps how much a PERCENTAGE discount can save in Naira, e.g. "20% off, up to
    # N5,000" - irrelevant for FIXED_AMOUNT coupons (already a hard cap).
    max_discount_amount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    min_order_amount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    max_redemptions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_redemptions_per_user: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    times_redeemed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Null = applies to every course. A course qualifies if it's in
    # applicable_course_ids OR matches applicable_category (either condition,
    # not both, is enough to qualify).
    applicable_course_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=True)
    applicable_category: Mapped[CourseCategoryEnum | None] = mapped_column(
        Enum(CourseCategoryEnum, name="course_category_enum", native_enum=True, create_type=False), nullable=True
    )

    new_users_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class CouponRedemption(BaseEntity):
    """Audit trail of a successful coupon use - backs the per-user redemption cap
    check and gives support a record of which coupon was used on which order."""

    __tablename__ = "coupon_redemptions"

    coupon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("coupons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    discount_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
