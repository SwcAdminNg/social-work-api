import enum
import uuid
from datetime import datetime

from pydantic import Field, model_validator

from app.common.base_dto import AuditDTO, BaseDTO, CreateDTO, UpdateDTO
from app.modules.support.entity import SupportSenderTypeEnum, SupportTicketStatusEnum
from app.modules.user.dto import UserReadDTO


class SupportAttachmentKindEnum(str, enum.Enum):
    IMAGE = "IMAGE"
    DOCUMENT = "DOCUMENT"


# ---------------------------------------------------------------------------
# FAQ
# ---------------------------------------------------------------------------


class FAQCategoryCreateDTO(CreateDTO):
    name: str = Field(max_length=150)
    order: int = 0


class FAQCategoryUpdateDTO(UpdateDTO):
    name: str | None = Field(default=None, max_length=150)
    order: int | None = None


class FAQCategoryReadDTO(AuditDTO):
    name: str
    order: int


class FAQItemCreateDTO(CreateDTO):
    category_id: uuid.UUID
    question: str = Field(max_length=500)
    answer: str
    order: int = 0
    is_published: bool = True


class FAQItemUpdateDTO(UpdateDTO):
    category_id: uuid.UUID | None = None
    question: str | None = Field(default=None, max_length=500)
    answer: str | None = None
    order: int | None = None
    is_published: bool | None = None


class FAQItemReadDTO(AuditDTO):
    category_id: uuid.UUID
    question: str
    answer: str
    order: int
    is_published: bool


class FAQCategoryWithItemsDTO(BaseDTO):
    id: uuid.UUID
    name: str
    order: int
    items: list[FAQItemReadDTO]


# ---------------------------------------------------------------------------
# Tickets / messages
# ---------------------------------------------------------------------------


class SupportTicketCreateDTO(CreateDTO):
    subject: str = Field(max_length=255)
    message: str = Field(min_length=1)


class SupportAttachmentUploadRequestDTO(CreateDTO):
    file_name: str = Field(max_length=255)
    content_type: str | None = None


class SupportAttachmentUploadResponseDTO(BaseDTO):
    upload_url: str
    storage_key: str


class SupportMessageCreateDTO(CreateDTO):
    body: str = Field(default="", max_length=5000)
    attachment_storage_key: str | None = Field(default=None, max_length=1000)
    attachment_file_name: str | None = Field(default=None, max_length=255)
    attachment_mime_type: str | None = Field(default=None, max_length=255)
    attachment_file_size_bytes: int | None = None

    @model_validator(mode="after")
    def _require_body_or_attachment(self) -> "SupportMessageCreateDTO":
        if not self.body.strip() and not self.attachment_storage_key:
            raise ValueError("A message needs a body, an attachment, or both")
        return self


class SupportMessageReadDTO(BaseDTO):
    id: uuid.UUID
    ticket_id: uuid.UUID
    sender_id: uuid.UUID
    sender_type: SupportSenderTypeEnum
    body: str
    created_at: datetime
    sender: UserReadDTO | None = None
    attachment_url: str | None = None
    attachment_file_name: str | None = None
    attachment_mime_type: str | None = None
    attachment_file_size_bytes: int | None = None
    attachment_kind: SupportAttachmentKindEnum | None = None


class SupportTicketReadDTO(BaseDTO):
    id: uuid.UUID
    user_id: uuid.UUID
    subject: str
    status: SupportTicketStatusEnum
    assigned_admin_id: uuid.UUID | None = None
    last_user_message_at: datetime | None = None
    last_admin_reply_at: datetime | None = None
    escalated_at: datetime | None = None
    rating: int | None = None
    rating_comment: str | None = None
    created_at: datetime
    user: UserReadDTO | None = None
    assigned_admin: UserReadDTO | None = None


class SupportTicketAssignDTO(BaseDTO):
    admin_id: uuid.UUID


class SupportTicketStatusUpdateDTO(BaseDTO):
    status: SupportTicketStatusEnum


class SupportTicketRatingDTO(BaseDTO):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)
