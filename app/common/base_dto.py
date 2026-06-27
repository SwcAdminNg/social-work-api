import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BaseDTO(BaseModel):
    """Root for every DTO. `from_attributes=True` lets these be built straight from
    SQLAlchemy entity instances (e.g. `UserReadDTO.model_validate(user_entity)`)."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CreateDTO(BaseDTO):
    """Marker base for "create" payloads. Intentionally empty: a create DTO should
    only ever contain the fields a client is allowed to set, never id/audit columns."""


class UpdateDTO(BaseDTO):
    """Marker base for "update" payloads. Subclasses should make every field optional
    so callers can send partial updates (PATCH semantics)."""


class AuditDTO(BaseDTO):
    """Read-only audit/soft-delete fields mirroring BaseEntity. Mix into a read DTO
    alongside the entity's own fields, e.g.:

        class UserReadDTO(AuditDTO):
            email: str
            full_name: str
    """

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime | None = None
    deleted_at: datetime | None = None
    restored_at: datetime | None = None
    created_by: uuid.UUID | None = None
    updated_by: uuid.UUID | None = None
    deleted_by: uuid.UUID | None = None
    restored_by: uuid.UUID | None = None
