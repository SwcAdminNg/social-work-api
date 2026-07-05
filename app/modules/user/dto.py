from datetime import datetime

from fastapi import Query
from pydantic import Field

from app.common.base_dto import AuditDTO, BaseDTO, UpdateDTO
from app.modules.user.entity import GenderEnum, PlatformEnum, UserTypeEnum


class UserReadDTO(AuditDTO):
    first_name: str
    last_name: str
    email: str
    username: str
    phone_number: str | None = None
    platform: PlatformEnum
    gender: GenderEnum | None = None
    user_type: UserTypeEnum
    address: str | None = None
    is_active: bool
    is_suspended: bool
    last_login_at: datetime | None = None


class UserUpdateDTO(UpdateDTO):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    username: str | None = Field(default=None, min_length=3, max_length=50)
    phone_number: str | None = Field(default=None, max_length=20)
    gender: GenderEnum | None = None
    address: str | None = Field(default=None, max_length=500)


class UserFilterParams:
    """Shared filter query params for the admin user listing. Use as a FastAPI
    dependency alongside `PaginationParams`."""

    def __init__(
        self,
        platform: PlatformEnum | None = Query(None, description="Filter by platform"),
        user_type: UserTypeEnum | None = Query(None, description="Filter by user type"),
        search: str | None = Query(
            None, description="Search by username, full name, email or phone number"
        ),
    ) -> None:
        self.platform = platform
        self.user_type = user_type
        self.search = search


class UserRoleUpdateDTO(BaseDTO):
    role: UserTypeEnum
