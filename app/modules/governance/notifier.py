import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notification.entity import NotificationTypeEnum
from app.modules.notification.service import NotificationService

logger = logging.getLogger(__name__)


@dataclass
class PendingNotification:
    user_ids: list[uuid.UUID]
    type: NotificationTypeEnum
    title: str
    body: str | None = None
    link: str | None = None
    metadata: dict = field(default_factory=dict)


class GovernanceNotifier:
    """Collects notifications during a workflow transition and sends them only
    after the transition has committed. A notification failure is logged and
    swallowed - it must never undo (or block) a review decision."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.pending: list[PendingNotification] = []

    def queue(
        self,
        user_ids,
        type: NotificationTypeEnum,
        title: str,
        body: str | None = None,
        link: str | None = None,
        exclude: set[uuid.UUID] | None = None,
        **metadata,
    ) -> None:
        recipients = [u for u in dict.fromkeys(user_ids) if u is not None and u not in (exclude or set())]
        if recipients:
            self.pending.append(
                PendingNotification(recipients, type, title, body, link, {k: str(v) for k, v in metadata.items()})
            )

    async def flush(self) -> None:
        service = NotificationService(self.session)
        for n in self.pending:
            try:
                await service.notify_many(n.user_ids, n.type, n.title, n.body, n.link, n.metadata or None)
            except Exception as exc:
                logger.warning("Failed to send governance notification %s: %s", n.type.value, exc)
                await self.session.rollback()
        self.pending.clear()
