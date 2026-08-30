import asyncio
import json
import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.cache as cache_module
from app.common.api_route import NoNullAPIRoute
from app.common.pagination import PaginatedResponse, PaginationParams
from app.common.responses import ApiResponse
from app.core import presence
from app.core.database import AsyncSessionLocal, get_db
from app.core.qstash import verify_qstash_signature
from app.modules.auth.dependencies import get_current_admin_user, get_current_user, get_user_from_token
from app.modules.support.dependencies import get_current_support_staff
from app.modules.support.dto import (
    FAQCategoryCreateDTO,
    FAQCategoryReadDTO,
    FAQCategoryUpdateDTO,
    FAQCategoryWithItemsDTO,
    FAQItemCreateDTO,
    FAQItemReadDTO,
    FAQItemUpdateDTO,
    SupportAttachmentUploadRequestDTO,
    SupportAttachmentUploadResponseDTO,
    SupportMessageCreateDTO,
    SupportMessageReadDTO,
    SupportTicketAssignDTO,
    SupportTicketCreateDTO,
    SupportTicketFilterParams,
    SupportTicketRatingDTO,
    SupportTicketReadDTO,
    SupportTicketStatusUpdateDTO,
)
from app.modules.support.service import FAQService, SupportService, ticket_channel
from app.modules.support.staff import is_support_staff
from app.modules.user.entity import User

router = APIRouter(prefix="/support", tags=["Support"], route_class=NoNullAPIRoute)

_PRESENCE_NAMESPACE = "support"


# ---------------------------------------------------------------------------
# FAQ - public read, admin CRUD
# ---------------------------------------------------------------------------


@router.get(
    "/faq",
    response_model=ApiResponse[list[FAQCategoryWithItemsDTO]],
    summary="Browse the public help center FAQ (no auth required)",
)
async def list_faq(db: AsyncSession = Depends(get_db)) -> ApiResponse[list[FAQCategoryWithItemsDTO]]:
    data = await FAQService(db).list_published_grouped()
    return ApiResponse(message="FAQ retrieved successfully", data=data)


@router.post(
    "/faq/categories",
    response_model=ApiResponse[FAQCategoryReadDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Create an FAQ category (admin only)",
)
async def create_faq_category(
    payload: FAQCategoryCreateDTO,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[FAQCategoryReadDTO]:
    category = await FAQService(db).create_category(payload)
    return ApiResponse(message="FAQ category created successfully", data=FAQCategoryReadDTO.model_validate(category))


@router.patch(
    "/faq/categories/{category_id}",
    response_model=ApiResponse[FAQCategoryReadDTO],
    summary="Update an FAQ category (admin only)",
)
async def update_faq_category(
    category_id: uuid.UUID,
    payload: FAQCategoryUpdateDTO,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[FAQCategoryReadDTO]:
    category = await FAQService(db).update_category(category_id, payload)
    return ApiResponse(message="FAQ category updated successfully", data=FAQCategoryReadDTO.model_validate(category))


@router.delete(
    "/faq/categories/{category_id}",
    response_model=ApiResponse[None],
    summary="Delete an FAQ category (admin only)",
)
async def delete_faq_category(
    category_id: uuid.UUID,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await FAQService(db).delete_category(category_id, current_user)
    return ApiResponse(message="FAQ category deleted successfully")


@router.get(
    "/faq/items",
    response_model=PaginatedResponse[FAQItemReadDTO],
    summary="List every FAQ item, published or not (admin only)",
)
async def list_faq_items_for_admin(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[FAQItemReadDTO]:
    items, total = await FAQService(db).list_items_for_admin(pagination)
    return PaginatedResponse.create(
        items=[FAQItemReadDTO.model_validate(i) for i in items], total_items=total, params=pagination
    )


@router.post(
    "/faq/items",
    response_model=ApiResponse[FAQItemReadDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Create an FAQ item (admin only)",
)
async def create_faq_item(
    payload: FAQItemCreateDTO,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[FAQItemReadDTO]:
    item = await FAQService(db).create_item(payload)
    return ApiResponse(message="FAQ item created successfully", data=FAQItemReadDTO.model_validate(item))


@router.patch(
    "/faq/items/{item_id}",
    response_model=ApiResponse[FAQItemReadDTO],
    summary="Update an FAQ item (admin only)",
)
async def update_faq_item(
    item_id: uuid.UUID,
    payload: FAQItemUpdateDTO,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[FAQItemReadDTO]:
    item = await FAQService(db).update_item(item_id, payload)
    return ApiResponse(message="FAQ item updated successfully", data=FAQItemReadDTO.model_validate(item))


@router.delete(
    "/faq/items/{item_id}",
    response_model=ApiResponse[None],
    summary="Delete an FAQ item (admin only)",
)
async def delete_faq_item(
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await FAQService(db).delete_item(item_id, current_user)
    return ApiResponse(message="FAQ item deleted successfully")


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------


@router.post(
    "/tickets",
    response_model=ApiResponse[SupportTicketReadDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Open a new support ticket/chat",
)
async def create_ticket(
    payload: SupportTicketCreateDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[SupportTicketReadDTO]:
    ticket = await SupportService(db).create_ticket(payload, current_user)
    return ApiResponse(message="Support ticket created successfully", data=ticket)


@router.get(
    "/tickets",
    response_model=PaginatedResponse[SupportTicketReadDTO],
    summary="List/filter the support ticket queue (admin or Support Desk member)",
)
async def list_tickets(
    pagination: PaginationParams = Depends(),
    filters: SupportTicketFilterParams = Depends(),
    current_user: User = Depends(get_current_support_staff),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[SupportTicketReadDTO]:
    items, total = await SupportService(db).list_for_admin(pagination, filters)
    return PaginatedResponse.create(items=items, total_items=total, params=pagination)


@router.get(
    "/tickets/mine",
    response_model=PaginatedResponse[SupportTicketReadDTO],
    summary="List the current user's own support tickets",
)
async def list_my_tickets(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[SupportTicketReadDTO]:
    items, total = await SupportService(db).list_my_tickets(current_user, pagination)
    return PaginatedResponse.create(items=items, total_items=total, params=pagination)


@router.get(
    "/tickets/{ticket_id}",
    response_model=ApiResponse[SupportTicketReadDTO],
    summary="Get a ticket (owner or admin)",
)
async def get_ticket(
    ticket_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[SupportTicketReadDTO]:
    ticket = await SupportService(db).get_ticket(ticket_id, current_user)
    return ApiResponse(message="Ticket retrieved successfully", data=ticket)


@router.get(
    "/tickets/{ticket_id}/messages",
    response_model=PaginatedResponse[SupportMessageReadDTO],
    summary="List a ticket's message history (owner or admin)",
)
async def list_ticket_messages(
    ticket_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[SupportMessageReadDTO]:
    items, total = await SupportService(db).list_messages(ticket_id, current_user, pagination)
    return PaginatedResponse.create(items=items, total_items=total, params=pagination)


@router.post(
    "/tickets/{ticket_id}/messages",
    response_model=ApiResponse[SupportMessageReadDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Post a message to a ticket (HTTP fallback for clients not using the WebSocket)",
)
async def post_ticket_message(
    ticket_id: uuid.UUID,
    payload: SupportMessageCreateDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[SupportMessageReadDTO]:
    message = await SupportService(db).post_message(ticket_id, payload, current_user)
    return ApiResponse(message="Message sent successfully", data=message)


@router.post(
    "/tickets/{ticket_id}/attachments/upload-url",
    response_model=ApiResponse[SupportAttachmentUploadResponseDTO],
    summary="Get a pre-signed URL to upload an image/document to attach to a message "
    "(owner or admin/Support Desk member)",
)
async def get_attachment_upload_url(
    ticket_id: uuid.UUID,
    payload: SupportAttachmentUploadRequestDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[SupportAttachmentUploadResponseDTO]:
    data = await SupportService(db).get_attachment_upload_url(ticket_id, payload, current_user)
    return ApiResponse(message="Upload URL generated successfully", data=data)


@router.post(
    "/tickets/{ticket_id}/assign",
    response_model=ApiResponse[SupportTicketReadDTO],
    summary="Assign/reassign a ticket to a staff member (admin or Support Desk member)",
)
async def assign_ticket(
    ticket_id: uuid.UUID,
    payload: SupportTicketAssignDTO,
    current_user: User = Depends(get_current_support_staff),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[SupportTicketReadDTO]:
    ticket = await SupportService(db).assign_ticket(ticket_id, payload.admin_id)
    return ApiResponse(message="Ticket assigned successfully", data=ticket)


@router.patch(
    "/tickets/{ticket_id}/status",
    response_model=ApiResponse[SupportTicketReadDTO],
    summary="Update a ticket's status, e.g. resolve/close (admin or Support Desk member)",
)
async def update_ticket_status(
    ticket_id: uuid.UUID,
    payload: SupportTicketStatusUpdateDTO,
    current_user: User = Depends(get_current_support_staff),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[SupportTicketReadDTO]:
    ticket = await SupportService(db).update_status(ticket_id, payload.status)
    return ApiResponse(message="Ticket status updated successfully", data=ticket)


@router.post(
    "/tickets/{ticket_id}/rating",
    response_model=ApiResponse[SupportTicketReadDTO],
    summary="Rate a resolved/closed support ticket (owner only)",
)
async def rate_ticket(
    ticket_id: uuid.UUID,
    payload: SupportTicketRatingDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[SupportTicketReadDTO]:
    ticket = await SupportService(db).submit_rating(ticket_id, payload, current_user)
    return ApiResponse(message="Thanks for your feedback!", data=ticket)


# ---------------------------------------------------------------------------
# Presence
# ---------------------------------------------------------------------------


@router.post(
    "/presence/heartbeat",
    response_model=ApiResponse[None],
    summary="Mark the current user online for support presence purposes (e.g. an admin "
    "with the ticket queue open but no specific ticket socket connected)",
)
async def presence_heartbeat(current_user: User = Depends(get_current_user)) -> ApiResponse[None]:
    await presence.mark_online(_PRESENCE_NAMESPACE, current_user.id)
    return ApiResponse(message="Presence updated successfully")


# ---------------------------------------------------------------------------
# WebSocket chat
# ---------------------------------------------------------------------------


@router.websocket("/tickets/{ticket_id}/ws")
async def ticket_chat_ws(websocket: WebSocket, ticket_id: uuid.UUID, token: str = Query(...)) -> None:
    async with AsyncSessionLocal() as db:
        user = await get_user_from_token(token, db)
        if user is None:
            await websocket.close(code=4401)
            return

        ticket = await SupportService(db).get_ticket_entity(ticket_id)
        if ticket is None:
            await websocket.close(code=4404)
            return
        if ticket.user_id != user.id and not await is_support_staff(user, db):
            await websocket.close(code=4403)
            return

    await websocket.accept()
    await presence.mark_online(_PRESENCE_NAMESPACE, user.id)

    async def reader() -> None:
        # HTTPException (e.g. 409 "ticket is closed") and pydantic ValidationError
        # (e.g. an empty body with no attachment) must never escape into Starlette's
        # HTTP exception middleware here - it doesn't know how to turn either into a
        # websocket frame and crashes the ASGI connection instead. Send a plain
        # error frame and keep the socket open so the client can react.
        async with AsyncSessionLocal() as reader_db:
            reader_service = SupportService(reader_db)
            while True:
                raw = await websocket.receive_text()
                try:
                    payload = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                await presence.mark_online(_PRESENCE_NAMESPACE, user.id)
                if payload.get("type") == "ping":
                    continue
                if payload.get("type") != "message":
                    continue
                try:
                    message_payload = SupportMessageCreateDTO(
                        body=payload.get("body", ""),
                        attachment_storage_key=payload.get("attachment_storage_key"),
                        attachment_file_name=payload.get("attachment_file_name"),
                        attachment_mime_type=payload.get("attachment_mime_type"),
                        attachment_file_size_bytes=payload.get("attachment_file_size_bytes"),
                    )
                    await reader_service.post_message(ticket_id, message_payload, user)
                except (HTTPException, ValidationError) as exc:
                    detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
                    await websocket.send_text(json.dumps({"type": "error", "detail": detail}))

    async def subscriber() -> None:
        """Relays every message published to this ticket's Redis channel - including
        the sender's own, once persisted - to this socket. If Redis isn't configured
        (local dev without it running), fall back to a no-op so the socket still
        accepts a connection, just without cross-connection fanout."""
        if cache_module.redis_client is None:
            await asyncio.Event().wait()
            return
        pubsub = cache_module.redis_client.pubsub()
        await pubsub.subscribe(ticket_channel(ticket_id))
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                await websocket.send_text(message["data"])
        finally:
            await pubsub.unsubscribe(ticket_channel(ticket_id))
            await pubsub.aclose()

    tasks = [asyncio.create_task(reader()), asyncio.create_task(subscriber())]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            error = task.exception()
            if error is not None and not isinstance(error, WebSocketDisconnect):
                raise error
    finally:
        for task in tasks:
            task.cancel()
        await presence.mark_offline(_PRESENCE_NAMESPACE, user.id)


# ---------------------------------------------------------------------------
# Cron (QStash)
# ---------------------------------------------------------------------------


@router.post(
    "/cron/check-escalation",
    summary="Cron endpoint that re-checks an unanswered ticket and escalates if still "
    "unanswered (via QStash)",
    include_in_schema=False,
)
async def check_escalation_cron(
    raw_body: bytes = Depends(verify_qstash_signature),
    db: AsyncSession = Depends(get_db),
) -> dict:
    payload = json.loads(raw_body)
    ticket_id = uuid.UUID(payload["ticket_id"])
    await SupportService(db).run_delayed_escalation_check(ticket_id)
    return {"status": "ok"}
