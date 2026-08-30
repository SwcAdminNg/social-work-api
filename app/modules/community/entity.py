import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity


class CommunityTypeEnum(str, enum.Enum):
    COURSE = "COURSE"
    GENERAL = "GENERAL"
    HELP = "HELP"
    CUSTOM = "CUSTOM"


class CommunityMembershipAddedViaEnum(str, enum.Enum):
    MANUAL = "MANUAL"
    COURSE_SNAPSHOT = "COURSE_SNAPSHOT"


class Community(BaseEntity):
    """A group-chat room. Every community - including the dynamic-membership types
    (COURSE/GENERAL/HELP) - gets a durable row here so messages, membership checks
    and WebSocket channels have a stable id to reference.

    Membership for COURSE/GENERAL/HELP is resolved dynamically (see
    `app/modules/community/membership.py`) rather than stored - a COURSE community's
    members are always exactly its course's current enrollees + instructors, a
    GENERAL/HELP community's members are always every active user. Only CUSTOM
    communities have real rows in `CommunityMembership`.

    `course_id` is unique among COURSE-type rows (enforced by a partial unique
    index in the migration, since it's NULL for every other type)."""

    __tablename__ = "communities"

    type: Mapped[CommunityTypeEnum] = mapped_column(
        Enum(CommunityTypeEnum, name="community_type_enum", native_enum=True), nullable=False, index=True
    )
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class CommunityMembership(BaseEntity):
    """Join table linking a `User` to a CUSTOM `Community`. Mirrors `GroupMembership`/
    `CourseInstructor`'s join-table shape: its own `BaseEntity`, plain FKs, no ORM
    `relationship()`. Never written to for COURSE/GENERAL/HELP communities."""

    __tablename__ = "community_memberships"

    community_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("communities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    added_via: Mapped[CommunityMembershipAddedViaEnum] = mapped_column(
        Enum(CommunityMembershipAddedViaEnum, name="community_membership_added_via_enum", native_enum=True),
        nullable=False,
    )
    # Which course's enrollee snapshot added them, for audit/UI ("added via Course
    # X's enrollees on <date>"). Null for MANUAL adds.
    added_from_course_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id"), nullable=True
    )


class CommunityMessage(BaseEntity):
    """`body` may be an empty string for an attachment-only or reference-only
    message (the DTO/service layer enforces that at least one of
    body/attachment/resource_reference is present). An attachment is uploaded
    directly to R2 via a presigned URL before the message referencing its
    `attachment_storage_key` is sent - same pattern as `SupportMessage`.

    `reply_to_message_id` is a flat self-reference (WhatsApp-style quote-reply,
    not a nested thread) - a reply to a reply still points at its own immediate
    parent, and the client renders one level of quoted snippet."""

    __tablename__ = "community_messages"

    community_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("communities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")

    reply_to_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("community_messages.id"), nullable=True, index=True
    )

    attachment_storage_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    attachment_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attachment_mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attachment_file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # A shared "curriculum/material" card - points at a Resource only (no
    # polymorphic reference type: the codebase already funnels shareable course
    # material through Resource, and doesn't use polymorphic associations
    # elsewhere - see app/modules/resource/entity.py).
    resource_reference_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resources.id"), nullable=True, index=True
    )

    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
