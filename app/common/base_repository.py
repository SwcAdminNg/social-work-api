import uuid
from typing import Generic, Sequence, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_entity import BaseEntity
from app.common.pagination import PaginationParams

ModelType = TypeVar("ModelType", bound=BaseEntity)


class BaseRepository(Generic[ModelType]):
    """Generic CRUD repository every entity-specific repository should inherit from.

    All read methods filter out soft-deleted rows (`deleted_at IS NULL`) by default
    so callers can't accidentally leak deleted records; pass `include_deleted=True`
    when you explicitly need them (e.g. an admin "trash" view or the restore flow).
    """

    model: type[ModelType]

    def __init__(self, session: AsyncSession, model: type[ModelType]) -> None:
        self.session = session
        self.model = model

    def _base_select(self, include_deleted: bool = False):
        stmt = select(self.model)
        if not include_deleted:
            stmt = stmt.where(self.model.deleted_at.is_(None))
        return stmt

    async def get_by_id(
        self, id: uuid.UUID, include_deleted: bool = False
    ) -> ModelType | None:
        stmt = self._base_select(include_deleted).where(self.model.id == id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self, pagination: PaginationParams, include_deleted: bool = False
    ) -> tuple[Sequence[ModelType], int]:
        count_stmt = select(func.count()).select_from(self._base_select(include_deleted).subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = self._base_select(include_deleted).offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total

    async def create(self, entity: ModelType) -> ModelType:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update(self, entity: ModelType) -> ModelType:
        await self.session.flush()
        # updated_at is generated server-side (onupdate=func.now()); refresh so the
        # in-memory entity reflects the real value instead of triggering a lazy
        # (sync) reload the next time it's accessed.
        await self.session.refresh(entity)
        return entity

    async def soft_delete(self, entity: ModelType, actor_id: uuid.UUID | None = None) -> ModelType:
        entity.mark_deleted(actor_id)
        await self.session.flush()
        return entity

    async def restore(self, entity: ModelType, actor_id: uuid.UUID | None = None) -> ModelType:
        entity.mark_restored(actor_id)
        await self.session.flush()
        return entity

    async def hard_delete(self, entity: ModelType) -> None:
        await self.session.delete(entity)
        await self.session.flush()
