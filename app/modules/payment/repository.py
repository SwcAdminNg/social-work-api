import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payment.entity import SavedCard, SubscriptionPlan, Transaction, UserSubscription


class PaymentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_plan_by_id(self, plan_id: uuid.UUID) -> SubscriptionPlan | None:
        return await self.session.get(SubscriptionPlan, plan_id)

    async def list_active_plans(self) -> Sequence[SubscriptionPlan]:
        stmt = select(SubscriptionPlan).where(SubscriptionPlan.is_active.is_(True))
        return (await self.session.execute(stmt)).scalars().all()

    async def get_transaction_by_reference(self, reference: str) -> Transaction | None:
        stmt = select(Transaction).where(Transaction.reference == reference)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_saved_card_by_id(self, card_id: uuid.UUID) -> SavedCard | None:
        return await self.session.get(SavedCard, card_id)

    async def list_user_saved_cards(self, user_id: uuid.UUID) -> Sequence[SavedCard]:
        stmt = select(SavedCard).where(SavedCard.user_id == user_id)
        return (await self.session.execute(stmt)).scalars().all()

    async def list_transactions(
        self, pagination
    ) -> tuple[Sequence[Transaction], int]:
        from sqlalchemy import func
        stmt = select(Transaction).order_by(Transaction.created_at.desc())
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total
