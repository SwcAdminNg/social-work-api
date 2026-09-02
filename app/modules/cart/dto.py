import uuid
from datetime import datetime

from pydantic import BaseModel

from app.modules.payment.entity import PaymentGatewayEnum


class AddCartItemRequest(BaseModel):
    course_id: uuid.UUID


class CheckoutCartRequest(BaseModel):
    coupon_code: str | None = None
    gateway: PaymentGatewayEnum = PaymentGatewayEnum.PAYSTACK
    save_card: bool = False


class CartItemReadDTO(BaseModel):
    course_id: uuid.UUID
    course_title: str
    course_slug: str
    course_thumbnail_url: str | None
    price: float
    added_at: datetime


class CartReadDTO(BaseModel):
    items: list[CartItemReadDTO]
    item_count: int
    subtotal_amount: float
