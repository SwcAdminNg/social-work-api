from pydantic import Field

from app.common.base_dto import AuditDTO, UpdateDTO
from app.modules.user.entity import GenderEnum, PlatformEnum


class UserReadDTO(AuditDTO):
    first_name: str
    last_name: str
    email: str
    username: str
    phone_number: str | None = None
    platform: PlatformEnum
    gender: GenderEnum | None = None
    address: str | None = None
    is_active: bool


class UserUpdateDTO(UpdateDTO):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone_number: str | None = Field(default=None, max_length=20)
    gender: GenderEnum | None = None
    address: str | None = Field(default=None, max_length=500)
