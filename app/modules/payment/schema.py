import uuid
from datetime import date, datetime

from fastapi import Query
from pydantic import BaseModel, Field

from app.common.pagination import PaginationMeta
from app.modules.payment.entity import PaymentGatewayEnum, TransactionStatusEnum, TransactionTypeEnum
from app.modules.user.dto import UserReadDTO


class InitializePaymentRequest(BaseModel):
    transaction_type: TransactionTypeEnum
    related_id: uuid.UUID | None = Field(None, description="Course ID or SubscriptionPlan ID")
    gateway: PaymentGatewayEnum = Field(default=PaymentGatewayEnum.PAYSTACK)
    save_card: bool = Field(default=False, description="Whether to save the card for future transactions")
    coupon_code: str | None = Field(None, description="Coupon code to apply (COURSE_PURCHASE only)")


class InitializePaymentResponse(BaseModel):
    authorization_url: str
    access_code: str
    reference: str


class ChargeSavedCardRequest(BaseModel):
    card_id: uuid.UUID
    transaction_type: TransactionTypeEnum
    related_id: uuid.UUID | None = None


class VerifyPaymentResponse(BaseModel):
    status: TransactionStatusEnum
    message: str


class SavedCardResponse(BaseModel):
    id: uuid.UUID
    gateway: PaymentGatewayEnum
    last4: str
    exp_month: str
    exp_year: str
    card_type: str
    bank: str | None
    is_default: bool


class SubscriptionPlanResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    duration_days: int
    price: float
    is_free_trial: bool
    is_active: bool


class TransactionReadDTO(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    amount: float
    subtotal_amount: float | None = None
    discount_amount: float = 0
    tax_rate: float = 0
    tax_amount: float = 0
    reference: str
    gateway: PaymentGatewayEnum
    status: TransactionStatusEnum
    transaction_type: TransactionTypeEnum
    related_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime | None = None
    user: UserReadDTO | None = None


class SubscriptionPlanCreateDTO(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    duration_days: int = Field(..., gt=0)
    price: float = Field(..., ge=0)
    is_free_trial: bool = False


class SubscriptionPlanUpdateDTO(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    duration_days: int | None = Field(None, gt=0)
    price: float | None = Field(None, ge=0)
    is_free_trial: bool | None = None
    is_active: bool | None = None


class ChangeSubscriptionPlanRequest(BaseModel):
    new_plan_id: uuid.UUID


class CurrentSubscriptionResponse(BaseModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    start_date: datetime
    end_date: datetime
    is_active: bool
    auto_renew: bool
    pending_plan_id: uuid.UUID | None
    plan: SubscriptionPlanResponse | None = None


class TaxFilterParams:
    """Shared optional date-range filter for the tax report. Use as a FastAPI
    dependency alongside `PaginationParams`."""

    def __init__(
        self,
        start_date: date | None = Query(None, description="Only include purchases made on or after this date"),
        end_date: date | None = Query(None, description="Only include purchases made on or before this date"),
    ) -> None:
        self.start_date = start_date
        self.end_date = end_date


class TaxRecordDTO(BaseModel):
    reference: str
    user_id: uuid.UUID
    transaction_type: TransactionTypeEnum
    subtotal_amount: float | None
    discount_amount: float
    tax_rate: float
    tax_amount: float
    amount: float
    created_at: datetime


class TaxSummaryDTO(BaseModel):
    tax_rate: float = Field(..., description="Current VAT rate applied to purchases")
    total_tax_amount: float = Field(..., description="Total VAT collected across every matching transaction, not just the current page")
    total_taxable_transactions: int
    start_date: date | None = None
    end_date: date | None = None


class TaxReportResponse(BaseModel):
    """Response for the admin tax report - a paginated list of taxed transactions
    plus a summary of the total VAT collected across the whole filtered range."""

    success: bool = True
    message: str = "OK"
    summary: TaxSummaryDTO
    data: list[TaxRecordDTO]
    meta: PaginationMeta
