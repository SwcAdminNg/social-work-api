from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.core.storage import get_r2_client
from app.modules.user.dto import ProfilePictureUploadRequest, ProfilePictureUploadResponse, UserFilterParams, UserUpdateDTO
from app.modules.user.entity import User
from app.modules.user.repository import UserRepository


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = UserRepository(session)

    async def update_profile(self, user: User, payload: UserUpdateDTO) -> User:
        if payload.username and payload.username.lower() != user.username.lower():
            if await self.repository.username_exists(payload.username):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, 
                    detail="Username already taken"
                )
                
        updates = payload.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(user, field, value)

        await self.repository.update(user)
        await self.session.commit()
        return user

    async def generate_profile_picture_upload_url(
        self, user: User, payload: ProfilePictureUploadRequest
    ) -> ProfilePictureUploadResponse:
        r2_client = get_r2_client()

        if user.profile_picture_url:
            from app.core.config import settings
            old_key = user.profile_picture_url.replace(f"{settings.r2_public_url.rstrip('/')}/", "")
            r2_client.delete_object(old_key)

        avatar_key = r2_client.build_avatar_key(user.id, payload.file_name)
        upload_url = r2_client.generate_upload_url(avatar_key, payload.content_type)

        public_url = r2_client.get_public_url(avatar_key)
        user.profile_picture_url = public_url
        await self.repository.update(user)
        await self.session.commit()

        return ProfilePictureUploadResponse(upload_url=upload_url, profile_picture_url=public_url)

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
