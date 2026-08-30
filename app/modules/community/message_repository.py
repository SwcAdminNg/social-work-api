import uuid
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_repository import BaseRepository
from app.common.pagination import PaginationParams
from app.modules.community.entity import CommunityMessage
from app.modules.resource.entity import Resource
from app.modules.user.entity import User


class CommunityMessageRepository(BaseRepository[CommunityMessage]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CommunityMessage)

    async def get_message_by_id(self, message_id: uuid.UUID) -> CommunityMessage | None:
        return await self.get_by_id(message_id)

    async def list_for_community(
        self, community_id: uuid.UUID, pagination: PaginationParams
    ) -> tuple[Sequence[CommunityMessage], int]:
        stmt = (
            self._base_select()
            .where(CommunityMessage.community_id == community_id)
            .order_by(CommunityMessage.created_at.desc())
        )
        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total

    async def bulk_load_context(
        self, messages: Sequence[CommunityMessage]
    ) -> tuple[dict[uuid.UUID, User], dict[uuid.UUID, CommunityMessage], dict[uuid.UUID, Resource]]:
        """One round-trip each for the sender/reply-parent/resource-reference of a
        page of messages, to avoid N+1 lookups when building read DTOs.

        `senders` covers both the page's own messages AND each reply-parent's
        sender - a quoted parent can be from an earlier page (outside `messages`),
        so its sender isn't necessarily already in the first set."""
        reply_ids = {m.reply_to_message_id for m in messages if m.reply_to_message_id is not None}

        reply_parents: dict[uuid.UUID, CommunityMessage] = {}
        if reply_ids:
            stmt = select(CommunityMessage).where(CommunityMessage.id.in_(reply_ids))
            reply_parents = {m.id: m for m in (await self.session.execute(stmt)).scalars().all()}

        sender_ids = {m.sender_id for m in messages} | {m.sender_id for m in reply_parents.values()}
        resource_ids = {m.resource_reference_id for m in messages if m.resource_reference_id is not None}

        senders: dict[uuid.UUID, User] = {}
        if sender_ids:
            stmt = select(User).where(User.id.in_(sender_ids))
            senders = {u.id: u for u in (await self.session.execute(stmt)).scalars().all()}

        resources: dict[uuid.UUID, Resource] = {}
        if resource_ids:
            stmt = select(Resource).where(Resource.id.in_(resource_ids))
            resources = {r.id: r for r in (await self.session.execute(stmt)).scalars().all()}

        return senders, reply_parents, resources
