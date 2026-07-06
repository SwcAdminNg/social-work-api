import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.payment.entity import PaymentGatewayEnum, TransactionStatusEnum, TransactionTypeEnum
from app.modules.user.dto import UserReadDTO


class InitializePaymentRequest(BaseModel):
    transaction_type: TransactionTypeEnum
    related_id: uuid.UUID | None = Field(None, description="Course ID or SubscriptionPlan ID")
    gateway: PaymentGatewayEnum = Field(default=PaymentGatewayEnum.PAYSTACK)
    save_card: bool = Field(default=False, description="Whether to save the card for future transactions")


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
