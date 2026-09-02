import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity


class PaymentGatewayEnum(str, enum.Enum):
    PAYSTACK = "PAYSTACK"
    STRIPE = "STRIPE"
    MONNIFY = "MONNIFY"


class TransactionStatusEnum(str, enum.Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class TransactionTypeEnum(str, enum.Enum):
    COURSE_PURCHASE = "COURSE_PURCHASE"
    SUBSCRIPTION = "SUBSCRIPTION"
    CART_PURCHASE = "CART_PURCHASE"


class SubscriptionPlan(BaseEntity):
    __tablename__ = "subscription_plans"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_days: Mapped[int] = mapped_column(nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    is_free_trial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class UserSubscription(BaseEntity):
    __tablename__ = "user_subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription_plans.id"), nullable=False, index=True
    )
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    pending_plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("subscription_plans.id"), nullable=True)


class Transaction(BaseEntity):
    __tablename__ = "transactions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    reference: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    gateway: Mapped[PaymentGatewayEnum] = mapped_column(
        Enum(PaymentGatewayEnum, name="payment_gateway_enum", native_enum=True), nullable=False
    )
    status: Mapped[TransactionStatusEnum] = mapped_column(
        Enum(TransactionStatusEnum, name="transaction_status_enum", native_enum=True),
        nullable=False,
        default=TransactionStatusEnum.PENDING,
    )
    transaction_type: Mapped[TransactionTypeEnum] = mapped_column(
        Enum(TransactionTypeEnum, name="transaction_type_enum", native_enum=True), nullable=False
    )
    related_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True) # Course ID or Plan ID
    gateway_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Coupon/discount bookkeeping. `amount` keeps its original meaning (the final
    # charged amount) so every pre-existing read of `amount` stays correct;
    # `subtotal_amount`/`discount_amount` are additive and null/0 for transactions
    # created before coupons existed.
    coupon_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("coupons.id", ondelete="SET NULL"), nullable=True
    )
    subtotal_amount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    discount_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0, server_default="0")


class SavedCard(BaseEntity):
    __tablename__ = "saved_cards"
    __table_args__ = (
        UniqueConstraint('user_id', 'signature', name='uq_saved_cards_user_signature'),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    gateway: Mapped[PaymentGatewayEnum] = mapped_column(
        Enum(PaymentGatewayEnum, name="payment_gateway_enum_card", native_enum=True), nullable=False
    )
    authorization_code: Mapped[str] = mapped_column(String(255), nullable=False)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    exp_month: Mapped[str] = mapped_column(String(2), nullable=False)
    exp_year: Mapped[str] = mapped_column(String(4), nullable=False)
    card_type: Mapped[str] = mapped_column(String(50), nullable=False)
    bank: Mapped[str | None] = mapped_column(String(100), nullable=True)
    signature: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class TransactionItem(BaseEntity):
    """One line item of a `CART_PURCHASE` transaction - one row per course. Unused
    for a single `COURSE_PURCHASE`, which keeps using `Transaction.related_id`
    exactly as before. `unit_price` snapshots the course's price at purchase time
    (before any coupon discount) so receipts stay accurate even if the course's
    price later changes."""

    __tablename__ = "transaction_items"

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False, index=True
    )
    unit_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
