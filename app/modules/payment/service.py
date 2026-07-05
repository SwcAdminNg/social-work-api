import uuid
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.course.access_entity import CourseAccessGrantedViaEnum, UserCourseAccess
from app.modules.course.repository import CourseRepository
from app.modules.payment.entity import (
    PaymentGatewayEnum,
    SavedCard,
    Transaction,
    TransactionStatusEnum,
    TransactionTypeEnum,
    UserSubscription,
)
from app.modules.payment.paystack_gateway import PaystackGateway
from app.modules.payment.repository import PaymentRepository
from app.modules.payment.schema import ChargeSavedCardRequest, InitializePaymentRequest
from app.modules.user.entity import User


class PaymentService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = PaymentRepository(session)
        self.course_repo = CourseRepository(session)
        
    def _get_gateway(self, gateway_type: PaymentGatewayEnum):
        if gateway_type == PaymentGatewayEnum.PAYSTACK:
            return PaystackGateway()
        raise NotImplementedError(f"Gateway {gateway_type} not implemented")

    def _generate_reference(self) -> str:
        return f"TXN_{secrets.token_hex(12).upper()}"

    async def initialize_payment(self, payload: InitializePaymentRequest, user: User) -> dict:
        amount = 0.0
        # Validate related ID
        if payload.transaction_type == TransactionTypeEnum.COURSE_PURCHASE:
            if not payload.related_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "related_id (course ID) is required for course purchase")
            course = await self.course_repo.get_by_id(payload.related_id)
            if not course:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
            if course.price is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Course is free, no payment required")
            amount = float(course.price)
                
        elif payload.transaction_type == TransactionTypeEnum.SUBSCRIPTION:
            if not payload.related_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "related_id (plan ID) is required for subscription")
            plan = await self.repo.get_plan_by_id(payload.related_id)
            if not plan:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")
            amount = float(plan.price)

        reference = self._generate_reference()
        gateway = self._get_gateway(payload.gateway)
        
        metadata = {
            "user_id": str(user.id),
            "transaction_type": payload.transaction_type.value,
            "related_id": str(payload.related_id) if payload.related_id else None,
            "save_card": payload.save_card,
        }

        # Call gateway API
        gateway_response = await gateway.initialize_transaction(
            amount=amount,
            email=user.email,
            reference=reference,
            metadata=metadata
        )

        # Create pending transaction
        transaction = Transaction(
            user_id=user.id,
            amount=amount,
            reference=reference,
            gateway=payload.gateway,
            status=TransactionStatusEnum.PENDING,
            transaction_type=payload.transaction_type,
            related_id=payload.related_id,
        )
        self.session.add(transaction)
        await self.session.commit()

        return gateway_response

    async def charge_saved_card(self, payload: ChargeSavedCardRequest, user: User) -> dict:
        card = await self.repo.get_saved_card_by_id(payload.card_id)
        if not card or card.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved card not found")

        amount = 0.0
        # Validate amount and related_id
        if payload.transaction_type == TransactionTypeEnum.COURSE_PURCHASE:
            course = await self.course_repo.get_by_id(payload.related_id)
            if not course or course.price is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid course or course is free")
            amount = float(course.price)
        elif payload.transaction_type == TransactionTypeEnum.SUBSCRIPTION:
            plan = await self.repo.get_plan_by_id(payload.related_id)
            if not plan:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid plan")
            amount = float(plan.price)

        reference = self._generate_reference()
        gateway = self._get_gateway(card.gateway)
        
        metadata = {
            "user_id": str(user.id),
            "transaction_type": payload.transaction_type.value,
            "related_id": str(payload.related_id) if payload.related_id else None,
            "save_card": False, # Card is already saved
        }

        # Create pending transaction
        transaction = Transaction(
            user_id=user.id,
            amount=amount,
            reference=reference,
            gateway=card.gateway,
            status=TransactionStatusEnum.PENDING,
            transaction_type=payload.transaction_type,
            related_id=payload.related_id,
        )
        self.session.add(transaction)
        await self.session.flush()

        # Charge via gateway
        try:
            charge_result = await gateway.charge_saved_card(
                authorization_code=card.authorization_code,
                amount=amount,
                email=user.email,
                reference=reference,
                metadata=metadata
            )
        except Exception as e:
            transaction.status = TransactionStatusEnum.FAILED
            await self.session.commit()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

        transaction.status = TransactionStatusEnum(charge_result["status"])
        transaction.gateway_response = charge_result.get("full_response")

        if transaction.status == TransactionStatusEnum.SUCCESS:
            await self._grant_access(transaction)

        await self.session.commit()
        return {"status": transaction.status.value, "reference": reference}

    async def verify_transaction(self, reference: str) -> Transaction:
        transaction = await self.repo.get_transaction_by_reference(reference)
        if not transaction:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")

        if transaction.status != TransactionStatusEnum.PENDING:
            return transaction # Already processed

        gateway = self._get_gateway(transaction.gateway)
        verify_result = await gateway.verify_transaction(reference)

        transaction.status = TransactionStatusEnum(verify_result["status"])
        transaction.gateway_response = verify_result.get("full_response")

        if transaction.status == TransactionStatusEnum.SUCCESS:
            # Grant access
            await self._grant_access(transaction)

            # Save card if requested and auth data exists
            metadata = transaction.gateway_response.get("metadata", {}) if transaction.gateway_response else {}
            auth_data = verify_result.get("authorization")
            
            if metadata.get("save_card") and auth_data and auth_data.get("reusable"):
                await self._save_card(transaction.user_id, transaction.gateway, auth_data)

        await self.session.commit()
        return transaction

    async def _grant_access(self, transaction: Transaction):
        if transaction.transaction_type == TransactionTypeEnum.COURSE_PURCHASE:
            access = UserCourseAccess(
                user_id=transaction.user_id,
                course_id=transaction.related_id,
                granted_via=CourseAccessGrantedViaEnum.PURCHASE
            )
            self.session.add(access)
            
        elif transaction.transaction_type == TransactionTypeEnum.SUBSCRIPTION:
            plan = await self.repo.get_plan_by_id(transaction.related_id)
            if plan:
                now = datetime.now(timezone.utc)
                end_date = now + timedelta(days=plan.duration_days)
                subscription = UserSubscription(
                    user_id=transaction.user_id,
                    plan_id=plan.id,
                    start_date=now,
                    end_date=end_date,
                    is_active=True
                )
                self.session.add(subscription)

    async def _save_card(self, user_id: uuid.UUID, gateway: PaymentGatewayEnum, auth_data: dict):
        signature = auth_data.get("signature")
        if signature:
            from sqlalchemy import select
            stmt = select(SavedCard).where(SavedCard.signature == signature)
            existing = (await self.session.execute(stmt)).scalar_one_or_none()
            if existing:
                return existing
        
        card = SavedCard(
            user_id=user_id,
            gateway=gateway,
            authorization_code=auth_data["authorization_code"],
            last4=auth_data.get("last4", "XXXX"),
            exp_month=auth_data.get("exp_month", "XX"),
            exp_year=auth_data.get("exp_year", "XXXX"),
            card_type=auth_data.get("card_type", "unknown"),
            bank=auth_data.get("bank"),
            signature=signature,
        )
        self.session.add(card)
        return card
