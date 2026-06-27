from typing import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_repository import BaseRepository
from app.common.pagination import PaginationParams
from app.modules.user.dto import UserFilterParams
from app.modules.user.entity import User


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def get_by_email(self, email: str) -> User | None:
        stmt = self._base_select().where(func.lower(User.email) == email.lower())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        stmt = self._base_select().where(func.lower(User.username) == username.lower())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email_or_username(self, identifier: str) -> User | None:
        stmt = self._base_select().where(
            (func.lower(User.email) == identifier.lower())
            | (func.lower(User.username) == identifier.lower())
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def email_exists(self, email: str) -> bool:
        return await self.get_by_email(email) is not None

    async def username_exists(self, username: str) -> bool:
        return await self.get_by_username(username) is not None

    async def list(
        self, pagination: PaginationParams, filters: UserFilterParams | None = None
    ) -> tuple[Sequence[User], int]:
        stmt = self._base_select()

        if filters is not None:
            if filters.platform is not None:
                stmt = stmt.where(User.platform == filters.platform)
            if filters.user_type is not None:
                stmt = stmt.where(User.user_type == filters.user_type)
            if filters.search is not None:
                term = f"%{filters.search}%"
                stmt = stmt.where(
                    or_(
                        User.username.ilike(term),
                        User.first_name.ilike(term),
                        User.last_name.ilike(term),
                        User.email.ilike(term),
                        User.phone_number.ilike(term),
                    )
                )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total
