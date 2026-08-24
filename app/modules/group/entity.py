import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity


class Group(BaseEntity):
    """A named group of users an admin manages (e.g. "Support Desk",
    "Management"), used to target notifications/escalations at the right
    staff without hard-coding roles. Membership is tracked in `GroupMembership`."""

    __tablename__ = "groups"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class GroupMembership(BaseEntity):
    """Join table linking a `User` to a `Group`. Mirrors `CourseInstructor`'s
    join-table shape: its own `BaseEntity`, plain FKs, no ORM `relationship()` -
    membership is queried explicitly via `GroupMembershipRepository`."""

    __tablename__ = "group_memberships"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_memberships_group_user"),)

    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
