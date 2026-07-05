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

    async def list_all_plans(self) -> Sequence[SubscriptionPlan]:
        stmt = select(SubscriptionPlan)
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
    ) -> tuple[Sequence[tuple[Transaction, "User"]], int]:
        from sqlalchemy import func
        from app.modules.user.entity import User
        stmt = (
            select(Transaction, User)
            .join(User, Transaction.user_id == User.id)
            .order_by(Transaction.created_at.desc())
        )
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).all()
        return items, total

    async def list_user_transactions(
        self, user_id: uuid.UUID, pagination
    ) -> tuple[Sequence[tuple[Transaction, "User"]], int]:
        from sqlalchemy import func
        from app.modules.user.entity import User
        stmt = (
            select(Transaction, User)
            .join(User, Transaction.user_id == User.id)
            .where(Transaction.user_id == user_id)
            .order_by(Transaction.created_at.desc())
        )
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).all()
        return items, total

    async def list_course_transactions_with_users(
        self, course_id: uuid.UUID, pagination
    ) -> tuple[Sequence[tuple[Transaction, "User"]], int]:
        from sqlalchemy import func
        from app.modules.user.entity import User
        from app.modules.payment.entity import TransactionTypeEnum
        stmt = (
            select(Transaction, User)
            .join(User, Transaction.user_id == User.id)
            .where(Transaction.related_id == course_id)
            .where(Transaction.transaction_type == TransactionTypeEnum.COURSE_PURCHASE)
            .order_by(Transaction.created_at.desc())
        )
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).all()
        return items, total

    async def get_subscriptions_expiring_in_days(
        self, days: int
    ) -> Sequence[tuple[UserSubscription, SubscriptionPlan, "User"]]:
        from datetime import datetime, timedelta, timezone
        from app.modules.user.entity import User
        from sqlalchemy import and_, cast, Date
        
        target_date = (datetime.now(timezone.utc) + timedelta(days=days)).date()
        
        stmt = (
            select(UserSubscription, SubscriptionPlan, User)
            .join(SubscriptionPlan, UserSubscription.plan_id == SubscriptionPlan.id)
            .join(User, UserSubscription.user_id == User.id)
            .where(
                and_(
                    UserSubscription.is_active.is_(True),
                    cast(UserSubscription.end_date, Date) == target_date
                )
            )
        )
        return (await self.session.execute(stmt)).all()

    async def get_subscriptions_expiring_today_or_past_due(
        self
    ) -> Sequence[tuple[UserSubscription, SubscriptionPlan, "User"]]:
        from datetime import datetime, timezone
        from app.modules.user.entity import User
        from sqlalchemy import and_
        
        now = datetime.now(timezone.utc)
        
        stmt = (
            select(UserSubscription, SubscriptionPlan, User)
            .join(SubscriptionPlan, UserSubscription.plan_id == SubscriptionPlan.id)
            .join(User, UserSubscription.user_id == User.id)
            .where(
                and_(
                    UserSubscription.is_active.is_(True),
                    UserSubscription.end_date <= now
                )
            )
        )
        return (await self.session.execute(stmt)).all()

    async def get_default_saved_card(self, user_id: uuid.UUID) -> SavedCard | None:
        stmt = (
            select(SavedCard)
            .where(SavedCard.user_id == user_id)
            .order_by(SavedCard.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()
