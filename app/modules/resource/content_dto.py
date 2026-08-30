import uuid

from pydantic import Field

from app.common.base_dto import AuditDTO, BaseDTO, CreateDTO, UpdateDTO
from app.modules.course.content_entity import VideoStatusEnum
from app.modules.resource.dto import ResourceReadDTO
from app.modules.resource.entity import ResourceAttachmentTypeEnum

# Fully generic, no course-specific fields - reused as-is rather than duplicated.
from app.modules.course.content_dto import (  # noqa: F401
    DocumentFinalizeDTO,
    DocumentUploadCredentialsDTO,
    VideoUploadCredentialsDTO,
)

# ---------------------------------------------------------------------------
# Attachments - create/update payloads
# ---------------------------------------------------------------------------


class ResourceAttachmentCreateDTO(CreateDTO):
    title: str = Field(min_length=1, max_length=255)
    attachment_type: ResourceAttachmentTypeEnum
    order_index: int = 0
    # Required only when attachment_type == DOCUMENT, used to build the R2 storage key.
    file_name: str | None = Field(default=None, max_length=255)
    downloadable: bool = False
    # Required only when attachment_type == LINKS.
    url: str | None = Field(default=None, max_length=2000)
    label: str | None = Field(default=None, max_length=255)
    description: str | None = None


class ResourceAttachmentUpdateDTO(UpdateDTO):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    order_index: int | None = None
    # Only settable when the attachment is a DOCUMENT.
    downloadable: bool | None = None
    # Only settable when the attachment is LINKS.
    url: str | None = Field(default=None, max_length=2000)
    label: str | None = Field(default=None, max_length=255)
    description: str | None = None


class AttachmentOrderEntryDTO(BaseDTO):
    id: uuid.UUID
    order_index: int


class ResourceAttachmentReorderDTO(BaseDTO):
    attachments: list[AttachmentOrderEntryDTO]


# ---------------------------------------------------------------------------
# Video / Document / Link - read shapes
# ---------------------------------------------------------------------------


class ResourceVideoDTO(BaseDTO):
    status: VideoStatusEnum
    playback_url: str | None = None
    thumbnail_url: str | None = None
    duration_seconds: int | None = None


class ResourceVideoManageDTO(ResourceVideoDTO):
    bunny_video_guid: str


class ResourceDocumentDTO(BaseDTO):
    file_name: str
    mime_type: str | None = None
    file_size_bytes: int | None = None
    is_uploaded: bool
    downloadable: bool


class ResourceDocumentManageDTO(ResourceDocumentDTO):
    storage_key: str


class ResourceLinkDTO(BaseDTO):
    url: str
    label: str | None = None
    description: str | None = None


# ---------------------------------------------------------------------------
# Attachments - read tiers
# ---------------------------------------------------------------------------


class ResourceAttachmentReadDTO(AuditDTO):
    resource_id: uuid.UUID
    title: str
    attachment_type: ResourceAttachmentTypeEnum
    order_index: int
    video: ResourceVideoDTO | None = None
    document: ResourceDocumentDTO | None = None
    link: ResourceLinkDTO | None = None


class ResourceAttachmentManageReadDTO(AuditDTO):
    resource_id: uuid.UUID
    title: str
    attachment_type: ResourceAttachmentTypeEnum
    order_index: int
    video: ResourceVideoManageDTO | None = None
    document: ResourceDocumentManageDTO | None = None
    link: ResourceLinkDTO | None = None


class ResourceDetailDTO(ResourceReadDTO):
    attachments: list[ResourceAttachmentReadDTO] = Field(default_factory=list)


class ResourceManageDetailDTO(ResourceReadDTO):
    attachments: list[ResourceAttachmentManageReadDTO] = Field(default_factory=list)
