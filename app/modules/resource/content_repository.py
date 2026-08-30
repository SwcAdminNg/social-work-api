import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.resource.content_entity import ResourceAttachment, ResourceDocument, ResourceLink, ResourceVideo


class ResourceContentRepository:
    """Read/write helpers for a resource's attachments (video/document/link).
    Mirrors `CourseContentRepository` - plain queries, no ORM relationships,
    assembled in Python by `ResourceContentService`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- attachments -------------------------------------------------------

    async def list_attachments(self, resource_id: uuid.UUID) -> Sequence[ResourceAttachment]:
        stmt = (
            select(ResourceAttachment)
            .where(ResourceAttachment.resource_id == resource_id, ResourceAttachment.deleted_at.is_(None))
            .order_by(ResourceAttachment.order_index)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def get_attachment(self, id: uuid.UUID) -> ResourceAttachment | None:
        stmt = select(ResourceAttachment).where(
            ResourceAttachment.id == id, ResourceAttachment.deleted_at.is_(None)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # -- video ---------------------------------------------------------------

    async def get_video_by_attachment(self, attachment_id: uuid.UUID) -> ResourceVideo | None:
        stmt = select(ResourceVideo).where(ResourceVideo.attachment_id == attachment_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_videos_for_attachments(self, attachment_ids: Sequence[uuid.UUID]) -> Sequence[ResourceVideo]:
        if not attachment_ids:
            return []
        stmt = select(ResourceVideo).where(ResourceVideo.attachment_id.in_(attachment_ids))
        return (await self.session.execute(stmt)).scalars().all()

    # -- document --------------------------------------------------------------

    async def get_document_by_attachment(self, attachment_id: uuid.UUID) -> ResourceDocument | None:
        stmt = select(ResourceDocument).where(ResourceDocument.attachment_id == attachment_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_documents_for_attachments(
        self, attachment_ids: Sequence[uuid.UUID]
    ) -> Sequence[ResourceDocument]:
        if not attachment_ids:
            return []
        stmt = select(ResourceDocument).where(ResourceDocument.attachment_id.in_(attachment_ids))
        return (await self.session.execute(stmt)).scalars().all()

    # -- link ------------------------------------------------------------------

    async def get_link_by_attachment(self, attachment_id: uuid.UUID) -> ResourceLink | None:
        stmt = select(ResourceLink).where(ResourceLink.attachment_id == attachment_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_links_for_attachments(self, attachment_ids: Sequence[uuid.UUID]) -> Sequence[ResourceLink]:
        if not attachment_ids:
            return []
        stmt = select(ResourceLink).where(ResourceLink.attachment_id.in_(attachment_ids))
        return (await self.session.execute(stmt)).scalars().all()
