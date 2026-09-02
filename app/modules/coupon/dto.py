import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.modules.coupon.entity import CouponDiscountTypeEnum
from app.modules.course.entity import CourseCategoryEnum


class CouponBaseDTO(BaseModel):
    code: str = Field(..., min_length=3, max_length=40)
    description: str | None = None
    discount_type: CouponDiscountTypeEnum
    discount_value: float = Field(..., gt=0)
    max_discount_amount: float | None = Field(None, gt=0)
    min_order_amount: float | None = Field(None, ge=0)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    max_redemptions: int | None = Field(None, gt=0)
    max_redemptions_per_user: int = Field(default=1, gt=0)
    applicable_course_ids: list[uuid.UUID] | None = None
    applicable_category: CourseCategoryEnum | None = None
    new_users_only: bool = False
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("discount_value")
    @classmethod
    def validate_percentage_range(cls, value: float, info) -> float:
        discount_type = info.data.get("discount_type")
        if discount_type == CouponDiscountTypeEnum.PERCENTAGE and value > 100:
            raise ValueError("A percentage discount cannot exceed 100")
        return value


class CouponCreateDTO(CouponBaseDTO):
    pass


class CouponUpdateDTO(BaseModel):
    code: str | None = Field(None, min_length=3, max_length=40)
    description: str | None = None
    discount_type: CouponDiscountTypeEnum | None = None
    discount_value: float | None = Field(None, gt=0)
    max_discount_amount: float | None = Field(None, gt=0)
    min_order_amount: float | None = Field(None, ge=0)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    max_redemptions: int | None = Field(None, gt=0)
    max_redemptions_per_user: int | None = Field(None, gt=0)
    applicable_course_ids: list[uuid.UUID] | None = None
    applicable_category: CourseCategoryEnum | None = None
    new_users_only: bool | None = None
    is_active: bool | None = None

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else value


class CouponReadDTO(BaseModel):
    id: uuid.UUID
    code: str
    description: str | None
    discount_type: CouponDiscountTypeEnum
    discount_value: float
    max_discount_amount: float | None
    min_order_amount: float | None
    valid_from: datetime | None
    valid_until: datetime | None
    max_redemptions: int | None
    max_redemptions_per_user: int
    times_redeemed: int
    applicable_course_ids: list[uuid.UUID] | None
    applicable_category: CourseCategoryEnum | None
    new_users_only: bool
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class CouponValidateRequest(BaseModel):
    code: str
    course_ids: list[uuid.UUID] | None = Field(
        None, description="Courses to price against. Defaults to the caller's current cart if omitted."
    )


class CouponValidateResponse(BaseModel):
    valid: bool = True
    code: str
    subtotal_amount: float
    discount_amount: float
    total_amount: float
    message: str = "Coupon applied"
