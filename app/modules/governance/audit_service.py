import enum
import uuid
from datetime import datetime, timezone
from typing import Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.modules.governance.entity import GovernanceAuditLog


class AuditEntityTypeEnum(str, enum.Enum):
    COURSE = "COURSE"
    COURSE_REVISION = "COURSE_REVISION"
    COURSE_VERSION = "COURSE_VERSION"
    STAFF_ROLE = "STAFF_ROLE"
    ESSAY_MARK = "ESSAY_MARK"


class AuditService:
    """Writes `governance_audit_log` rows. `record` only adds to the session -
    it never commits - so the audit row lands in the *same* transaction as the
    state change it describes: either both persist or neither does."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def record(
        self,
        *,
        actor_id: uuid.UUID | None,
        action: str,
        entity_type: AuditEntityTypeEnum,
        entity_id: uuid.UUID,
        course_id: uuid.UUID | None = None,
        revision_id: uuid.UUID | None = None,
        version_label: str | None = None,
        from_status: str | None = None,
        to_status: str | None = None,
        comment: str | None = None,
        actor_permissions: Iterable | None = None,
        metadata: dict | None = None,
    ) -> GovernanceAuditLog:
        row = GovernanceAuditLog(
            id=uuid.uuid4(),
            occurred_at=datetime.now(timezone.utc),
            actor_id=actor_id,
            actor_permissions=sorted(
                (p.value if isinstance(p, enum.Enum) else str(p)) for p in (actor_permissions or [])
            ),
            entity_type=entity_type.value,
            entity_id=entity_id,
            course_id=course_id,
            revision_id=revision_id,
            version_label=version_label,
            action=action,
            from_status=_value(from_status),
            to_status=_value(to_status),
            comment=comment,
            metadata_json=metadata,
        )
        self.session.add(row)
        return row

    async def list(
        self,
        pagination: PaginationParams,
        course_id: uuid.UUID | None = None,
        revision_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
        entity_type: AuditEntityTypeEnum | None = None,
        entity_id: uuid.UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> tuple[Sequence[GovernanceAuditLog], int]:
        stmt = select(GovernanceAuditLog)
        if course_id is not None:
            stmt = stmt.where(GovernanceAuditLog.course_id == course_id)
        if revision_id is not None:
            stmt = stmt.where(GovernanceAuditLog.revision_id == revision_id)
        if actor_id is not None:
            stmt = stmt.where(GovernanceAuditLog.actor_id == actor_id)
        if entity_type is not None:
            stmt = stmt.where(GovernanceAuditLog.entity_type == entity_type.value)
        if entity_id is not None:
            stmt = stmt.where(GovernanceAuditLog.entity_id == entity_id)
        if date_from is not None:
            stmt = stmt.where(GovernanceAuditLog.occurred_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(GovernanceAuditLog.occurred_at <= date_to)

        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        stmt = stmt.order_by(GovernanceAuditLog.occurred_at.desc()).offset(pagination.offset).limit(pagination.limit)
        return (await self.session.execute(stmt)).scalars().all(), total


def _value(v) -> str | None:
    if v is None:
        return None
    return v.value if isinstance(v, enum.Enum) else str(v)
