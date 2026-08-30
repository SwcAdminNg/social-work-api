import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity
from app.modules.course.content_entity import VideoProviderEnum, VideoStatusEnum
from app.modules.resource.entity import ResourceAttachmentTypeEnum


class ResourceAttachment(BaseEntity):
    """One video/document/link on a Resource. Mirrors `CourseItem`, but a
    Resource can hold several of these (unlike a CourseItem's 1:1 with its
    single video/document/link child row)."""

    __tablename__ = "resource_attachments"

    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resources.id"), nullable=False, index=True
    )
    attachment_type: Mapped[ResourceAttachmentTypeEnum] = mapped_column(
        Enum(ResourceAttachmentTypeEnum, name="resource_attachment_type_enum", native_enum=True), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ResourceVideo(BaseEntity):
    __tablename__ = "resource_videos"

    attachment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resource_attachments.id"), unique=True, nullable=False, index=True
    )
    # Reuses the course module's video_provider_enum/video_status_enum native
    # Postgres types (create_type=False below) rather than minting duplicates -
    # same Bunny-hosted-video lifecycle, no reason for two DB enum types.
    provider: Mapped[VideoProviderEnum] = mapped_column(
        Enum(VideoProviderEnum, name="video_provider_enum", native_enum=True, create_type=False),
        nullable=False,
        default=VideoProviderEnum.BUNNY,
    )
    bunny_video_guid: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[VideoStatusEnum] = mapped_column(
        Enum(VideoStatusEnum, name="video_status_enum", native_enum=True, create_type=False),
        nullable=False,
        default=VideoStatusEnum.PENDING,
    )
    playback_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ResourceDocument(BaseEntity):
    __tablename__ = "resource_documents"

    attachment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resource_attachments.id"), unique=True, nullable=False, index=True
    )
    storage_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_uploaded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    downloadable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")


class ResourceLink(BaseEntity):
    __tablename__ = "resource_links"

    attachment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resource_attachments.id"), unique=True, nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
