from datetime import date

from fastapi import Query
from pydantic import EmailStr, Field

from app.common.base_dto import AuditDTO, CreateDTO
from app.modules.user.entity import PlatformEnum


class ContactUsCreateDTO(CreateDTO):
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone_number: str = Field(min_length=1, max_length=20)
    company_name: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1)
    platform: PlatformEnum


class ContactUsReadDTO(AuditDTO):
    full_name: str
    email: str
    phone_number: str
    company_name: str
    message: str
    platform: PlatformEnum


class ContactUsFilterParams:
    """Shared filter query params for listing contact us messages. Use as a FastAPI
    dependency alongside `PaginationParams`."""

    def __init__(
        self,
        platform: PlatformEnum | None = Query(None, description="Filter by platform"),
        search: str | None = Query(
            None, description="Search by full name, email or phone number"
        ),
        start_date: date | None = Query(None, description="Filter messages created on or after this date"),
        end_date: date | None = Query(None, description="Filter messages created on or before this date"),
    ) -> None:
        self.platform = platform
        self.search = search
        self.start_date = start_date
        self.end_date = end_date
