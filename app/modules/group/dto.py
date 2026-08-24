import uuid
from datetime import datetime

from pydantic import Field

from app.common.base_dto import AuditDTO, BaseDTO, CreateDTO, UpdateDTO
from app.modules.user.dto import UserReadDTO


class GroupCreateDTO(CreateDTO):
    name: str = Field(max_length=100)
    description: str | None = Field(default=None, max_length=500)


class GroupUpdateDTO(UpdateDTO):
    name: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class GroupReadDTO(AuditDTO):
    name: str
    description: str | None = None
    is_active: bool


class GroupMemberAddDTO(BaseDTO):
    user_id: uuid.UUID


class GroupMemberReadDTO(BaseDTO):
    id: uuid.UUID
    group_id: uuid.UUID
    user_id: uuid.UUID
    user: UserReadDTO
    created_at: datetime
