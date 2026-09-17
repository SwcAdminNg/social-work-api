from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_repository import BaseRepository
from app.common.pagination import PaginationParams
from app.modules.instructor_application.entity import InstructorApplication, InstructorApplicationStatusEnum


class InstructorApplicationRepository(BaseRepository[InstructorApplication]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, InstructorApplication)

    async def has_pending_for_email(self, email: str) -> bool:
        stmt = self._base_select().where(
            func.lower(InstructorApplication.email) == email.lower(),
            InstructorApplication.status == InstructorApplicationStatusEnum.PENDING,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def list_by_status(
        self, pagination: PaginationParams, status: InstructorApplicationStatusEnum | None = None
    ):
        stmt = self._base_select()
        if status is not None:
            stmt = stmt.where(InstructorApplication.status == status)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(InstructorApplication.created_at.desc()).offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total
