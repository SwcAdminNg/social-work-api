import uuid
from datetime import datetime

from app.common.base_dto import AuditDTO, BaseDTO
from app.modules.notification.entity import NotificationTypeEnum


class NotificationReadDTO(AuditDTO):
    type: NotificationTypeEnum
    title: str
    body: str | None = None
    link: str | None = None
    metadata_json: dict | None = None
    is_read: bool
    read_at: datetime | None = None


class UnreadCountReadDTO(BaseDTO):
    unread_count: int
