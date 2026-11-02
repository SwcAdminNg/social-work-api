from datetime import date

from fastapi import Query
from pydantic import EmailStr, Field, field_validator

from app.common.base_dto import AuditDTO, CreateDTO
from app.modules.user.entity import PlatformEnum
from app.modules.contact_us.entity import ContactUsCategoryEnum


class ContactUsCreateDTO(CreateDTO):
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone_number: str | None = Field(default=None, max_length=20)
    company_name: str | None = Field(default=None, max_length=200)
    message: str = Field(min_length=1)
    platform: PlatformEnum
    category: ContactUsCategoryEnum | None = None
    subject: str | None = Field(default=None, max_length=255)
    # Path of the page the form was submitted from, e.g. "/contact".
    source_page: str | None = Field(default=None, max_length=255)

    @field_validator("phone_number", "source_page", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class ContactUsReadDTO(AuditDTO):
    full_name: str
    email: str
    phone_number: str | None = None
    company_name: str | None
    message: str
    platform: PlatformEnum
    category: ContactUsCategoryEnum | None = None
    subject: str | None = None
    source_page: str | None = None


class ContactUsFilterParams:
    """Shared filter query params for listing contact us messages. Use as a FastAPI
    dependency alongside `PaginationParams`."""

    def __init__(
        self,
        platform: PlatformEnum | None = Query(None, description="Filter by platform"),
        category: ContactUsCategoryEnum | None = Query(None, description="Filter by category"),
        source_page: str | None = Query(
            None, description="Filter by the page the message was sent from, e.g. /contact"
        ),
        search: str | None = Query(
            None, description="Search by full name, email or phone number"
        ),
        start_date: date | None = Query(None, description="Filter messages created on or after this date"),
        end_date: date | None = Query(None, description="Filter messages created on or before this date"),
    ) -> None:
        self.platform = platform
        self.category = category
        self.source_page = source_page
        self.search = search
        self.start_date = start_date
        self.end_date = end_date
