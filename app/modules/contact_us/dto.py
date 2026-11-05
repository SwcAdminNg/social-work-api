import re
from datetime import date

from fastapi import Query
from pydantic import EmailStr, Field, computed_field, field_validator

from app.common.base_dto import AuditDTO, BaseDTO, CreateDTO
from app.modules.user.entity import PlatformEnum
from app.modules.contact_us.entity import CONTACT_CATEGORY_LABELS, ContactUsCategoryEnum

MESSAGE_MAX_LENGTH = 5000
DETAILS_MAX_ITEMS = 20


class ContactDetailDTO(BaseDTO):
    """One labelled answer from a richer form, e.g. {"label": "Country", "value": "Nigeria"}."""

    label: str = Field(min_length=1, max_length=60)
    value: str = Field(min_length=1, max_length=1000)

    @field_validator("label", "value", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value
_PHONE_CHARS = re.compile(r"^\+?[\d\s().-]+$")


class ContactUsCreateDTO(CreateDTO):
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    # Optional; international formats are accepted (7 to 15 digits, with
    # spaces, dots, dashes or brackets), without a Nigeria-only length rule.
    phone_number: str | None = Field(default=None, max_length=32)
    company_name: str | None = Field(default=None, max_length=200)
    message: str = Field(min_length=1, max_length=MESSAGE_MAX_LENGTH)
    platform: PlatformEnum
    category: ContactUsCategoryEnum | None = None
    subject: str | None = Field(default=None, max_length=255)
    # Path of the page the form was submitted from, e.g. "/contact".
    source_page: str | None = Field(default=None, max_length=255)
    details: list[ContactDetailDTO] | None = Field(default=None, max_length=DETAILS_MAX_ITEMS)
    # Spam trap: the public forms include a hidden "website" field that people
    # never see. Anything in it marks the submission as automated. Never stored.
    website: str | None = Field(default=None, max_length=500, exclude=True)

    @field_validator("full_name", "message", "subject", "company_name", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("phone_number", "source_page", "subject", "company_name", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    @field_validator("phone_number")
    @classmethod
    def _valid_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        digits = re.sub(r"\D", "", value)
        if not _PHONE_CHARS.match(value) or not 7 <= len(digits) <= 15:
            raise ValueError("Enter a valid phone number, including the country code, or leave it blank.")
        return value

    @field_validator("details", mode="before")
    @classmethod
    def _drop_blank_details(cls, value: object) -> object:
        # Optional questions left blank arrive as empty values; leave them out.
        if isinstance(value, list):
            kept = [
                item for item in value
                if not (isinstance(item, dict) and not str(item.get("value") or "").strip())
            ]
            return kept or None
        return value

    @property
    def is_spam(self) -> bool:
        return bool(self.website and self.website.strip())


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
    details: list[ContactDetailDTO] | None = None
    # Short reference such as "SWCL-1A2B3C4D", shown to the visitor on success.
    reference: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def category_label(self) -> str | None:
        return CONTACT_CATEGORY_LABELS.get(self.category) if self.category else None


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
            None, description="Search by full name, email, phone number or reference (SWCL-XXXXXXXX)"
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
