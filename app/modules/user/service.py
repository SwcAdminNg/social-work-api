from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.user.dto import UserUpdateDTO
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
