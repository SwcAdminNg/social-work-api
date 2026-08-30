import enum
import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.common.base_dto import AuditDTO, BaseDTO, CreateDTO
from app.modules.community.entity import CommunityMembershipAddedViaEnum, CommunityTypeEnum
from app.modules.resource.dto import ResourceCardDTO
from app.modules.user.dto import UserReadDTO


class CommunityAttachmentKindEnum(str, enum.Enum):
    IMAGE = "IMAGE"
    DOCUMENT = "DOCUMENT"


# ---------------------------------------------------------------------------
# Communities
# ---------------------------------------------------------------------------


class CommunityReadDTO(AuditDTO):
    type: CommunityTypeEnum
    course_id: uuid.UUID | None = None
    name: str
    description: str | None = None
    is_active: bool
    member_count: int | None = None


class CustomCommunityCreateDTO(CreateDTO):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    user_ids: list[uuid.UUID] = Field(default_factory=list)
    # Course ids whose current enrollees + instructors are snapshotted in as
    # COURSE_SNAPSHOT members at creation time - a one-time snapshot, not a live
    # sync. A user who enrolls in the course later is not auto-added.
    course_snapshot_ids: list[uuid.UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_some_members(self) -> "CustomCommunityCreateDTO":
        if not self.user_ids and not self.course_snapshot_ids:
            raise ValueError("A custom community needs at least one user or course snapshot")
        return self


class CommunityMembersAddDTO(CreateDTO):
    user_ids: list[uuid.UUID] = Field(default_factory=list)
    course_snapshot_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _require_some_members(self) -> "CommunityMembersAddDTO":
        if not self.user_ids and self.course_snapshot_id is None:
            raise ValueError("Provide at least one user_id or a course_snapshot_id")
        return self


class CommunityMemberReadDTO(BaseDTO):
    """`added_via`/`added_from_course_id` are only meaningful for CUSTOM
    communities (where membership is an explicit, auditable row) - null for
    COURSE/GENERAL/HELP members, whose membership is derived dynamically from
    enrollment/instructor status or simply "is an active user"."""

    user: UserReadDTO
    added_via: CommunityMembershipAddedViaEnum | None = None
    added_from_course_id: uuid.UUID | None = None
    is_online: bool = False


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


class CommunityMessageCreateDTO(CreateDTO):
    body: str = Field(default="", max_length=5000)
    reply_to_message_id: uuid.UUID | None = None
    resource_reference_id: uuid.UUID | None = None
    attachment_storage_key: str | None = Field(default=None, max_length=1000)
    attachment_file_name: str | None = Field(default=None, max_length=255)
    attachment_mime_type: str | None = Field(default=None, max_length=255)
    attachment_file_size_bytes: int | None = None

    @model_validator(mode="after")
    def _require_content(self) -> "CommunityMessageCreateDTO":
        if not self.body.strip() and not self.attachment_storage_key and not self.resource_reference_id:
            raise ValueError("A message needs a body, an attachment, or a shared reference")
        return self


class CommunityMessageQuoteDTO(BaseDTO):
    """Denormalized snippet of the message being replied to, so the client doesn't
    need a second round-trip - including a lookup on the parent's sender - just to
    render the quoted preview (e.g. "Replying to Ada Obi: ...")."""

    id: uuid.UUID
    sender_id: uuid.UUID
    sender: UserReadDTO | None = None
    body: str
    attachment_file_name: str | None = None


class CommunityMessageReadDTO(BaseDTO):
    id: uuid.UUID
    community_id: uuid.UUID
    sender_id: uuid.UUID
    sender: UserReadDTO | None = None
    body: str
    created_at: datetime
    reply_to: CommunityMessageQuoteDTO | None = None
    attachment_url: str | None = None
    attachment_file_name: str | None = None
    attachment_mime_type: str | None = None
    attachment_file_size_bytes: int | None = None
    attachment_kind: CommunityAttachmentKindEnum | None = None
    resource_reference: ResourceCardDTO | None = None


class CommunityAttachmentUploadRequestDTO(CreateDTO):
    file_name: str = Field(max_length=255)
    content_type: str | None = None


class CommunityAttachmentUploadResponseDTO(BaseDTO):
    upload_url: str
    storage_key: str


class CommunityUnreadCountReadDTO(BaseDTO):
    total_unread: int


# ---------------------------------------------------------------------------
# WebSocket-only frames (never persisted)
# ---------------------------------------------------------------------------


class CommunityTypingEventDTO(BaseDTO):
    type: Literal["typing"] = "typing"
    community_id: uuid.UUID
    user_id: uuid.UUID
    is_typing: bool


# ---------------------------------------------------------------------------
# Presence
# ---------------------------------------------------------------------------


class CommunityOnlineMembersReadDTO(BaseDTO):
    online_user_ids: list[uuid.UUID]
