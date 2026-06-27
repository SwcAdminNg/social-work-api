import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BaseEntity(Base):
    """Abstract base every table entity inherits from.

    Provides the audit/soft-delete columns shared by all tables: id, created_at,
    updated_at, deleted_at, restored_at and the *_by actor columns. The *_by columns
    are plain UUID references (no FK) so this base has no dependency on a users table.
    """

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    restored_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def mark_deleted(self, actor_id: uuid.UUID | None = None) -> None:
        self.deleted_at = datetime.now(timezone.utc)
        self.deleted_by = actor_id
        self.restored_at = None
        self.restored_by = None

    def mark_restored(self, actor_id: uuid.UUID | None = None) -> None:
        self.restored_at = datetime.now(timezone.utc)
        self.restored_by = actor_id
        self.deleted_at = None
        self.deleted_by = None
