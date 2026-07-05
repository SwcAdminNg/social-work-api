import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.payment.entity import PaymentGatewayEnum, TransactionStatusEnum, TransactionTypeEnum


class InitializePaymentRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Amount to be paid in local currency")
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
    amount: float = Field(..., gt=0)
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
