from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.modules.user.dto import UserFilterParams, UserUpdateDTO
from app.modules.user.entity import User
from app.modules.user.repository import UserRepository


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = UserRepository(session)

    async def update_profile(self, user: User, payload: UserUpdateDTO) -> User:
        updates = payload.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(user, field, value)

        await self.repository.update(user)
        await self.session.commit()
        return user

    async def list(
        self, pagination: PaginationParams, filters: UserFilterParams | None = None
    ) -> tuple[Sequence[User], int]:
        return await self.repository.list(pagination, filters)

    async def get_by_id(self, id: str) -> User | None:
        return await self.repository.get_by_id(id)

    async def set_suspend_status(self, user: User, is_suspended: bool) -> User:
        user.is_suspended = is_suspended
        await self.repository.update(user)
        await self.session.commit()
        return user

    async def update_role(self, user: User, role: str) -> User:
        user.user_type = role
        await self.repository.update(user)
        await self.session.commit()
        return user
