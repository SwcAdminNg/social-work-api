import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.core.config import settings
from app.core.email import email_service
from app.core.qstash import get_qstash_client
from app.core.storage import get_r2_client
from app.core import presence
from app.core.ws_pubsub import channel_name, publish_event
from app.modules.group.repository import GroupMembershipRepository, GroupRepository
from app.modules.support.dto import (
    FAQCategoryCreateDTO,
    FAQCategoryUpdateDTO,
    FAQCategoryWithItemsDTO,
    FAQItemCreateDTO,
    FAQItemReadDTO,
    FAQItemUpdateDTO,
    SupportAttachmentKindEnum,
    SupportAttachmentUploadRequestDTO,
    SupportAttachmentUploadResponseDTO,
    SupportMessageCreateDTO,
    SupportMessageReadDTO,
    SupportTicketCreateDTO,
    SupportTicketFilterParams,
    SupportTicketRatingDTO,
    SupportTicketReadDTO,
)
from app.modules.support.entity import (
    FAQCategory,
    FAQItem,
    SupportMessage,
    SupportSenderTypeEnum,
    SupportTicket,
    SupportTicketStatusEnum,
)
from app.modules.support.repository import (
    FAQCategoryRepository,
    FAQItemRepository,
    SupportMessageRepository,
    SupportTicketRepository,
)
from app.modules.support.staff import SUPPORT_DESK_GROUP_NAME, is_support_staff
from app.modules.user.dto import UserReadDTO
from app.modules.user.entity import User
from app.modules.user.repository import UserRepository

logger = logging.getLogger(__name__)

_PRESENCE_NAMESPACE = "support"
_TICKET_CHANNEL_NAMESPACE = "support:ticket"


def ticket_channel(ticket_id: uuid.UUID) -> str:
    return channel_name(_TICKET_CHANNEL_NAMESPACE, ticket_id)


async def publish_ticket_event(ticket_id: uuid.UUID, event: dict) -> None:
    await publish_event(_TICKET_CHANNEL_NAMESPACE, ticket_id, event)


class FAQService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.category_repo = FAQCategoryRepository(session)
        self.item_repo = FAQItemRepository(session)

    async def list_published_grouped(self) -> list[FAQCategoryWithItemsDTO]:
        categories = await self.category_repo.list_ordered()
        items = await self.item_repo.list_published()
        items_by_category: dict[uuid.UUID, list[FAQItemReadDTO]] = {}
        for item in items:
            items_by_category.setdefault(item.category_id, []).append(FAQItemReadDTO.model_validate(item))
        return [
            FAQCategoryWithItemsDTO(
                id=c.id, name=c.name, order=c.order, items=items_by_category.get(c.id, [])
            )
            for c in categories
        ]

    async def create_category(self, payload: FAQCategoryCreateDTO) -> FAQCategory:
        category = FAQCategory(**payload.model_dump())
        await self.category_repo.create(category)
        await self.session.commit()
        return category

    async def update_category(self, category_id: uuid.UUID, payload: FAQCategoryUpdateDTO) -> FAQCategory:
        category = await self.category_repo.get_by_id(category_id)
        if category is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "FAQ category not found")
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(category, field, value)
        await self.category_repo.update(category)
        await self.session.commit()
        return category

    async def delete_category(self, category_id: uuid.UUID, current_user: User) -> None:
        category = await self.category_repo.get_by_id(category_id)
        if category is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "FAQ category not found")
        await self.category_repo.soft_delete(category, current_user.id)
        await self.session.commit()

    async def list_items_for_admin(self, pagination: PaginationParams) -> tuple[list[FAQItem], int]:
        items, total = await self.item_repo.list_all_for_admin(pagination)
        return list(items), total

    async def create_item(self, payload: FAQItemCreateDTO) -> FAQItem:
        if await self.category_repo.get_by_id(payload.category_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "FAQ category not found")
        item = FAQItem(**payload.model_dump())
        await self.item_repo.create(item)
        await self.session.commit()
        return item

    async def update_item(self, item_id: uuid.UUID, payload: FAQItemUpdateDTO) -> FAQItem:
        item = await self.item_repo.get_by_id(item_id)
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "FAQ item not found")
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(item, field, value)
        await self.item_repo.update(item)
        await self.session.commit()
        return item

    async def delete_item(self, item_id: uuid.UUID, current_user: User) -> None:
        item = await self.item_repo.get_by_id(item_id)
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "FAQ item not found")
        await self.item_repo.soft_delete(item, current_user.id)
        await self.session.commit()


class SupportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.ticket_repo = SupportTicketRepository(session)
        self.message_repo = SupportMessageRepository(session)
        self.user_repo = UserRepository(session)
        self.group_repo = GroupRepository(session)
        self.membership_repo = GroupMembershipRepository(session)

    async def _ensure_can_access(self, ticket: SupportTicket, current_user: User) -> None:
        if ticket.user_id == current_user.id:
            return
        if not await is_support_staff(current_user, self.session):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have access to this ticket")

    async def get_ticket_entity(self, ticket_id: uuid.UUID) -> SupportTicket | None:
        """Raw lookup (no 404/authorization) - used by the WebSocket handshake in
        `router.py`, which needs to distinguish "not found" from "forbidden" itself
        to close the socket with the right code."""
        return await self.ticket_repo.get_by_id(ticket_id)

    async def _get_ticket_or_404(self, ticket_id: uuid.UUID) -> SupportTicket:
        ticket = await self.get_ticket_entity(ticket_id)
        if ticket is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Support ticket not found")
        return ticket

    async def _build_message_dto(self, message: SupportMessage) -> SupportMessageReadDTO:
        sender = await self.user_repo.get_by_id(message.sender_id)
        attachment_url = None
        attachment_kind = None
        if message.attachment_storage_key:
            attachment_url = get_r2_client().get_public_url(message.attachment_storage_key)
            attachment_kind = (
                SupportAttachmentKindEnum.IMAGE
                if (message.attachment_mime_type or "").startswith("image/")
                else SupportAttachmentKindEnum.DOCUMENT
            )
        return SupportMessageReadDTO(
            id=message.id,
            ticket_id=message.ticket_id,
            sender_id=message.sender_id,
            sender_type=message.sender_type,
            body=message.body,
            created_at=message.created_at,
            sender=UserReadDTO.model_validate(sender) if sender else None,
            attachment_url=attachment_url,
            attachment_file_name=message.attachment_file_name,
            attachment_mime_type=message.attachment_mime_type,
            attachment_file_size_bytes=message.attachment_file_size_bytes,
            attachment_kind=attachment_kind,
        )

    async def _build_ticket_dto(self, ticket: SupportTicket) -> SupportTicketReadDTO:
        user = await self.user_repo.get_by_id(ticket.user_id)
        assigned_admin = (
            await self.user_repo.get_by_id(ticket.assigned_admin_id) if ticket.assigned_admin_id else None
        )
        return SupportTicketReadDTO(
            id=ticket.id,
            user_id=ticket.user_id,
            subject=ticket.subject,
            status=ticket.status,
            assigned_admin_id=ticket.assigned_admin_id,
            last_user_message_at=ticket.last_user_message_at,
            last_admin_reply_at=ticket.last_admin_reply_at,
            escalated_at=ticket.escalated_at,
            rating=ticket.rating,
            rating_comment=ticket.rating_comment,
            created_at=ticket.created_at,
            user=UserReadDTO.model_validate(user) if user else None,
            assigned_admin=UserReadDTO.model_validate(assigned_admin) if assigned_admin else None,
        )

    # -- creation / messaging -------------------------------------------------

    async def create_ticket(self, payload: SupportTicketCreateDTO, current_user: User) -> SupportTicketReadDTO:
        now = datetime.now(timezone.utc)
        ticket = SupportTicket(
            user_id=current_user.id,
            subject=payload.subject,
            status=SupportTicketStatusEnum.OPEN,
            last_user_message_at=now,
        )
        await self.ticket_repo.create(ticket)

        message = SupportMessage(
            ticket_id=ticket.id,
            sender_id=current_user.id,
            sender_type=SupportSenderTypeEnum.USER,
            body=payload.message,
        )
        await self.message_repo.create(message)
        await self.session.commit()

        await self._check_and_maybe_escalate(ticket)
        await publish_ticket_event(
            ticket.id, {"type": "message", "data": (await self._build_message_dto(message)).model_dump(mode="json")}
        )
        return await self._build_ticket_dto(ticket)

    async def post_message(
        self, ticket_id: uuid.UUID, payload: SupportMessageCreateDTO, current_user: User
    ) -> SupportMessageReadDTO:
        ticket = await self._get_ticket_or_404(ticket_id)
        await self._ensure_can_access(ticket, current_user)

        if ticket.status in (SupportTicketStatusEnum.RESOLVED, SupportTicketStatusEnum.CLOSED):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "This ticket is closed - please start a new ticket"
            )

        is_staff_sender = await is_support_staff(current_user, self.session)
        now = datetime.now(timezone.utc)

        message = SupportMessage(
            ticket_id=ticket.id,
            sender_id=current_user.id,
            sender_type=SupportSenderTypeEnum.ADMIN if is_staff_sender else SupportSenderTypeEnum.USER,
            body=payload.body,
            attachment_storage_key=payload.attachment_storage_key,
            attachment_file_name=payload.attachment_file_name,
            attachment_mime_type=payload.attachment_mime_type,
            attachment_file_size_bytes=payload.attachment_file_size_bytes,
        )
        await self.message_repo.create(message)

        if is_staff_sender:
            ticket.last_admin_reply_at = now
            ticket.escalated_at = None
            if ticket.status == SupportTicketStatusEnum.OPEN:
                ticket.status = SupportTicketStatusEnum.IN_PROGRESS
        else:
            ticket.last_user_message_at = now
        await self.ticket_repo.update(ticket)
        await self.session.commit()

        if not is_staff_sender:
            await self._check_and_maybe_escalate(ticket)

        message_dto = await self._build_message_dto(message)
        await publish_ticket_event(ticket.id, {"type": "message", "data": message_dto.model_dump(mode="json")})
        return message_dto

    # -- admin management --------------------------------------------------------

    async def assign_ticket(self, ticket_id: uuid.UUID, admin_id: uuid.UUID) -> SupportTicketReadDTO:
        """`admin_id` may be an ADMIN or an INSTRUCTOR who is a Support Desk member -
        anyone `is_support_staff` accepts, not just literal admins."""
        ticket = await self._get_ticket_or_404(ticket_id)
        assignee = await self.user_repo.get_by_id(admin_id)
        if assignee is None or not await is_support_staff(assignee, self.session):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Support staff user not found")
        ticket.assigned_admin_id = assignee.id
        await self.ticket_repo.update(ticket)
        await self.session.commit()
        await publish_ticket_event(ticket.id, {"type": "assigned", "admin_id": str(assignee.id)})
        return await self._build_ticket_dto(ticket)

    async def update_status(self, ticket_id: uuid.UUID, status_value: SupportTicketStatusEnum) -> SupportTicketReadDTO:
        ticket = await self._get_ticket_or_404(ticket_id)
        ticket.status = status_value
        await self.ticket_repo.update(ticket)
        await self.session.commit()
        await publish_ticket_event(ticket.id, {"type": "status_changed", "status": status_value.value})
        return await self._build_ticket_dto(ticket)

    async def list_for_admin(
        self,
        pagination: PaginationParams,
        filters: SupportTicketFilterParams,
    ) -> tuple[list[SupportTicketReadDTO], int]:
        items, total = await self.ticket_repo.list_for_admin(pagination, filters)
        return [await self._build_ticket_dto(t) for t in items], total

    # -- user-facing -------------------------------------------------------------

    async def list_my_tickets(
        self, user: User, pagination: PaginationParams
    ) -> tuple[list[SupportTicketReadDTO], int]:
        items, total = await self.ticket_repo.list_for_user(user.id, pagination)
        return [await self._build_ticket_dto(t) for t in items], total

    async def get_ticket(self, ticket_id: uuid.UUID, current_user: User) -> SupportTicketReadDTO:
        ticket = await self._get_ticket_or_404(ticket_id)
        await self._ensure_can_access(ticket, current_user)
        return await self._build_ticket_dto(ticket)

    async def list_messages(
        self, ticket_id: uuid.UUID, current_user: User, pagination: PaginationParams
    ) -> tuple[list[SupportMessageReadDTO], int]:
        ticket = await self._get_ticket_or_404(ticket_id)
        await self._ensure_can_access(ticket, current_user)
        items, total = await self.message_repo.list_for_ticket(ticket_id, pagination)
        return [await self._build_message_dto(m) for m in items], total

    async def get_attachment_upload_url(
        self, ticket_id: uuid.UUID, payload: SupportAttachmentUploadRequestDTO, current_user: User
    ) -> SupportAttachmentUploadResponseDTO:
        """Mints a presigned R2 upload URL for a file the caller is about to attach
        to their next message - same two-step flow as `CourseDocument`: the client
        PUTs bytes directly to `upload_url`, then references `storage_key` in the
        `SupportMessageCreateDTO` it sends over HTTP or the WebSocket."""
        ticket = await self._get_ticket_or_404(ticket_id)
        await self._ensure_can_access(ticket, current_user)

        r2 = get_r2_client()
        storage_key = r2.build_support_attachment_key(ticket.id, payload.file_name)
        upload_url = r2.generate_upload_url(storage_key, payload.content_type)
        return SupportAttachmentUploadResponseDTO(upload_url=upload_url, storage_key=storage_key)

    async def submit_rating(
        self, ticket_id: uuid.UUID, payload: SupportTicketRatingDTO, current_user: User
    ) -> SupportTicketReadDTO:
        ticket = await self._get_ticket_or_404(ticket_id)
        if ticket.user_id != current_user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only rate your own ticket")
        if ticket.status not in (SupportTicketStatusEnum.RESOLVED, SupportTicketStatusEnum.CLOSED):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This ticket has not been resolved yet")
        if ticket.rating is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "This ticket has already been rated")

        ticket.rating = payload.rating
        ticket.rating_comment = payload.comment
        ticket.rated_at = datetime.now(timezone.utc)
        await self.ticket_repo.update(ticket)
        await self.session.commit()
        return await self._build_ticket_dto(ticket)

    # -- escalation ----------------------------------------------------------------

    def _dashboard_link(self, ticket_id: uuid.UUID) -> str:
        return f"{settings.frontend_url.rstrip('/')}/admin/support/tickets/{ticket_id}"

    async def _send_escalation_email(self, ticket: SupportTicket, member_ids: list[uuid.UUID]) -> None:
        for member_id in member_ids:
            member = await self.user_repo.get_by_id(member_id)
            if member is None:
                continue
            await email_service.send_support_escalation_email(
                to_email=member.email,
                first_name=member.first_name,
                ticket_subject=ticket.subject,
                dashboard_link=self._dashboard_link(ticket.id),
            )

    async def _schedule_delayed_escalation_check(self, ticket_id: uuid.UUID) -> None:
        if not settings.qstash_token:
            return
        try:
            client = get_qstash_client()
            await client.message.publish_json(
                url=f"{settings.api_base_url.rstrip('/')}/support/cron/check-escalation",
                body={"ticket_id": str(ticket_id)},
                delay=settings.support_escalation_minutes * 60,
            )
        except Exception as exc:
            logger.warning("Failed to schedule delayed escalation check for ticket %s: %s", ticket_id, exc)

    async def _check_and_maybe_escalate(self, ticket: SupportTicket) -> None:
        group = await self.group_repo.get_by_name(SUPPORT_DESK_GROUP_NAME)
        if group is None:
            logger.warning("'%s' group not found - skipping support escalation", SUPPORT_DESK_GROUP_NAME)
            return

        member_ids = await self.membership_repo.get_active_user_ids_in_group(group.id)
        staff_online = await presence.any_online(_PRESENCE_NAMESPACE, member_ids)

        if not staff_online and ticket.escalated_at is None:
            await self._send_escalation_email(ticket, member_ids)
            ticket.escalated_at = datetime.now(timezone.utc)
            await self.ticket_repo.update(ticket)
            await self.session.commit()

        if ticket.escalated_at is None:
            await self._schedule_delayed_escalation_check(ticket.id)

    async def run_delayed_escalation_check(self, ticket_id: uuid.UUID) -> None:
        """Fired by the `/support/cron/check-escalation` QStash callback scheduled
        in `_check_and_maybe_escalate`. Re-checks at fire time (rather than trusting
        the schedule blindly) whether the ticket is still unanswered, so a stale job
        can't re-send an email after an admin already replied or the ticket closed."""
        ticket = await self.ticket_repo.get_by_id(ticket_id)
        if ticket is None or ticket.escalated_at is not None:
            return
        if ticket.status in (SupportTicketStatusEnum.RESOLVED, SupportTicketStatusEnum.CLOSED):
            return
        still_unanswered = ticket.last_admin_reply_at is None or (
            ticket.last_user_message_at is not None and ticket.last_admin_reply_at < ticket.last_user_message_at
        )
        if not still_unanswered:
            return

        group = await self.group_repo.get_by_name(SUPPORT_DESK_GROUP_NAME)
        if group is None:
            return
        member_ids = await self.membership_repo.get_active_user_ids_in_group(group.id)
        await self._send_escalation_email(ticket, member_ids)
        ticket.escalated_at = datetime.now(timezone.utc)
        await self.ticket_repo.update(ticket)
        await self.session.commit()
