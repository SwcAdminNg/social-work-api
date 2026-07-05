import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
import json

from app.common.api_route import NoNullAPIRoute
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.core.qstash import verify_qstash_signature
from app.modules.auth.dependencies import get_current_user
from app.modules.payment.schema import (
    ChargeSavedCardRequest,
    InitializePaymentRequest,
    InitializePaymentResponse,
    SavedCardResponse,
    SubscriptionPlanResponse,
    VerifyPaymentResponse,
)
from app.modules.payment.service import PaymentService
from app.modules.payment.repository import PaymentRepository
from app.modules.user.entity import User

router = APIRouter(prefix="/payments", tags=["Payments"], route_class=NoNullAPIRoute)


@router.post(
    "/initialize",
    response_model=ApiResponse[InitializePaymentResponse],
    summary="Initialize a new payment transaction",
)
async def initialize_payment(
    payload: InitializePaymentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[InitializePaymentResponse]:
    data = await PaymentService(db).initialize_payment(payload, current_user)
    return ApiResponse(message="Payment initialized", data=InitializePaymentResponse(**data))


@router.post(
    "/charge-card",
    response_model=ApiResponse[dict],
    summary="Charge a previously saved card",
)
async def charge_saved_card(
    payload: ChargeSavedCardRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    data = await PaymentService(db).charge_saved_card(payload, current_user)
    return ApiResponse(message="Charge attempted", data=data)


@router.get(
    "/verify/{reference}",
    response_model=ApiResponse[VerifyPaymentResponse],
    summary="Verify a transaction by reference",
)
async def verify_payment(
    reference: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[VerifyPaymentResponse]:
    # Can be public or authenticated. Usually client calls this after successful redirect.
    transaction = await PaymentService(db).verify_transaction(reference)
    data = VerifyPaymentResponse(status=transaction.status, message="Payment verified")
    return ApiResponse(message="Verification complete", data=data)


@router.post(
    "/webhook",
    summary="Webhook endpoint for payment gateways (via QStash)",
    include_in_schema=False,
)
async def payment_webhook(
    raw_body: bytes = Depends(verify_qstash_signature),
    db: AsyncSession = Depends(get_db),
) -> dict:
    body_text = raw_body.decode("utf-8")
    try:
        payload = json.loads(body_text) if body_text else {}
    except json.JSONDecodeError:
        payload = {}
    
    event = payload.get("event")
    if event == "charge.success":
        reference = payload.get("data", {}).get("reference")
        if reference:
            # Re-using verify_transaction logic since it calls Paystack directly for truth
            await PaymentService(db).verify_transaction(reference)

    return {"status": "ok"}


@router.get(
    "/cards",
    response_model=ApiResponse[list[SavedCardResponse]],
    summary="List user's saved cards",
)
async def list_saved_cards(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[SavedCardResponse]]:
    cards = await PaymentRepository(db).list_user_saved_cards(current_user.id)
    data = [SavedCardResponse.model_validate(card, from_attributes=True) for card in cards]
    return ApiResponse(message="Saved cards retrieved", data=data)


@router.get(
    "/plans",
    response_model=ApiResponse[list[SubscriptionPlanResponse]],
    summary="List available subscription plans",
)
async def list_plans(
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[SubscriptionPlanResponse]]:
    plans = await PaymentRepository(db).list_active_plans()
    data = [SubscriptionPlanResponse.model_validate(plan, from_attributes=True) for plan in plans]
    return ApiResponse(message="Plans retrieved", data=data)
