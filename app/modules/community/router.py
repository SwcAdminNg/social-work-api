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
from app.core.ws_pubsub import channel_name, publish_event
from app.modules.auth.dependencies import get_current_admin_user, get_current_user, get_user_from_token
from app.modules.community import membership
from app.modules.community.dto import (
    CommunityAttachmentUploadRequestDTO,
    CommunityAttachmentUploadResponseDTO,
    CommunityMemberReadDTO,
    CommunityMembersAddDTO,
    CommunityMessageCreateDTO,
    CommunityMessageReadDTO,
    CommunityOnlineMembersReadDTO,
    CommunityReadDTO,
    CommunityUnreadCountReadDTO,
    CustomCommunityCreateDTO,
)
from app.modules.community.service import CommunityService
from app.modules.user.entity import User

router = APIRouter(prefix="/community", tags=["Community"], route_class=NoNullAPIRoute)

_PRESENCE_NAMESPACE = "community"
_CHANNEL_NAMESPACE = "community"


# ---------------------------------------------------------------------------
# Communities
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=ApiResponse[list[CommunityReadDTO]],
    summary="List every community the current user belongs to (General, Help, their "
    "course communities, and any custom communities they're a member of)",
)
async def list_communities(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[CommunityReadDTO]]:
    data = await CommunityService(db).list_for_user(current_user)
    return ApiResponse(message="Communities retrieved successfully", data=data)


@router.post(
    "/custom",
    response_model=ApiResponse[CommunityReadDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom community, optionally seeding it with users and/or a "
    "one-time snapshot of a course's current enrollees (admin only)",
)
async def create_custom_community(
    payload: CustomCommunityCreateDTO,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CommunityReadDTO]:
    data = await CommunityService(db).create_custom(payload, current_user)
    return ApiResponse(message="Community created successfully", data=data)


@router.get(
    "/custom",
    response_model=PaginatedResponse[CommunityReadDTO],
    summary="List/search every custom community (admin only)",
)
async def list_custom_communities(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(None, description="Search by community name"),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[CommunityReadDTO]:
    items, total = await CommunityService(db).list_custom_for_admin(pagination, search)
    return PaginatedResponse.create(items=items, total_items=total, params=pagination)


@router.get(
    "/unread-count",
    response_model=ApiResponse[CommunityUnreadCountReadDTO],
    summary="Total unread message count across every community the current user "
    "belongs to (for a header/nav badge)",
)
async def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CommunityUnreadCountReadDTO]:
    # Registered before the "/{community_id}" routes below - a path param route
    # would otherwise swallow this and try (and fail) to parse "unread-count" as a UUID.
    data = await CommunityService(db).get_unread_count(current_user)
    return ApiResponse(message="Unread count retrieved successfully", data=data)


@router.get(
    "/{community_id}",
    response_model=ApiResponse[CommunityReadDTO],
    summary="Get a community (member or admin)",
)
async def get_community(
    community_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CommunityReadDTO]:
    data = await CommunityService(db).get_community(community_id, current_user)
    return ApiResponse(message="Community retrieved successfully", data=data)


@router.get(
    "/{community_id}/members",
    response_model=PaginatedResponse[CommunityMemberReadDTO],
    summary="List a community's members, with online status (member or admin)",
)
async def list_community_members(
    community_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[CommunityMemberReadDTO]:
    items, total = await CommunityService(db).list_members(community_id, pagination, current_user)
    return PaginatedResponse.create(items=items, total_items=total, params=pagination)


@router.post(
    "/{community_id}/members",
    response_model=ApiResponse[None],
    summary="Add users and/or a course's current enrollees (one-time snapshot) to a "
    "custom community (admin only)",
)
async def add_community_members(
    community_id: uuid.UUID,
    payload: CommunityMembersAddDTO,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await CommunityService(db).add_members(community_id, payload, current_user)
    return ApiResponse(message="Members added successfully")


@router.delete(
    "/{community_id}/members/{user_id}",
    response_model=ApiResponse[None],
    summary="Remove a member from a custom community (admin only)",
)
async def remove_community_member(
    community_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await CommunityService(db).remove_member(community_id, user_id, current_user)
    return ApiResponse(message="Member removed successfully")


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


@router.get(
    "/{community_id}/messages",
    response_model=PaginatedResponse[CommunityMessageReadDTO],
    summary="List a community's message history, most recent first (member)",
)
async def list_community_messages(
    community_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[CommunityMessageReadDTO]:
    items, total = await CommunityService(db).list_messages(community_id, current_user, pagination)
    return PaginatedResponse.create(items=items, total_items=total, params=pagination)


@router.post(
    "/{community_id}/messages",
    response_model=ApiResponse[CommunityMessageReadDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Post a message to a community (HTTP fallback for clients not using the WebSocket)",
)
async def post_community_message(
    community_id: uuid.UUID,
    payload: CommunityMessageCreateDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CommunityMessageReadDTO]:
    message = await CommunityService(db).post_message(community_id, payload, current_user)
    return ApiResponse(message="Message sent successfully", data=message)


@router.post(
    "/{community_id}/attachments/upload-url",
    response_model=ApiResponse[CommunityAttachmentUploadResponseDTO],
    summary="Get a pre-signed URL to upload an image/document to attach to a message (member)",
)
async def get_attachment_upload_url(
    community_id: uuid.UUID,
    payload: CommunityAttachmentUploadRequestDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CommunityAttachmentUploadResponseDTO]:
    data = await CommunityService(db).get_attachment_upload_url(community_id, payload, current_user)
    return ApiResponse(message="Upload URL generated successfully", data=data)


# ---------------------------------------------------------------------------
# Presence
# ---------------------------------------------------------------------------


@router.get(
    "/{community_id}/online",
    response_model=ApiResponse[CommunityOnlineMembersReadDTO],
    summary="List which of a community's members are currently online (member)",
)
async def list_online_members(
    community_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CommunityOnlineMembersReadDTO]:
    data = await CommunityService(db).list_online_members(community_id, current_user)
    return ApiResponse(message="Online members retrieved successfully", data=data)


@router.post(
    "/{community_id}/read",
    response_model=ApiResponse[None],
    summary="Mark a community as read up to now, for the current user (clears its "
    "contribution to /community/unread-count)",
)
async def mark_community_read(
    community_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await CommunityService(db).mark_read(community_id, current_user)
    return ApiResponse(message="Marked as read")


@router.post(
    "/presence/heartbeat",
    response_model=ApiResponse[None],
    summary="Mark the current user online for community presence purposes",
)
async def presence_heartbeat(current_user: User = Depends(get_current_user)) -> ApiResponse[None]:
    await presence.mark_online(_PRESENCE_NAMESPACE, current_user.id)
    return ApiResponse(message="Presence updated successfully")


# ---------------------------------------------------------------------------
# WebSocket chat
# ---------------------------------------------------------------------------


@router.websocket("/{community_id}/ws")
async def community_chat_ws(websocket: WebSocket, community_id: uuid.UUID, token: str = Query(...)) -> None:
    async with AsyncSessionLocal() as db:
        user = await get_user_from_token(token, db)
        if user is None:
            await websocket.close(code=4401)
            return

        community = await CommunityService(db).get_community_entity(community_id)
        if community is None:
            await websocket.close(code=4404)
            return
        if not await membership.is_member(db, community, user):
            await websocket.close(code=4403)
            return

    await websocket.accept()
    await presence.mark_online(_PRESENCE_NAMESPACE, user.id)

    async def reader() -> None:
        # HTTPException and pydantic ValidationError must never escape into
        # Starlette's HTTP exception middleware here - it doesn't know how to turn
        # either into a websocket frame and crashes the ASGI connection instead.
        # Send a plain error frame and keep the socket open so the client can react.
        async with AsyncSessionLocal() as reader_db:
            reader_service = CommunityService(reader_db)
            while True:
                raw = await websocket.receive_text()
                try:
                    payload = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                await presence.mark_online(_PRESENCE_NAMESPACE, user.id)
                frame_type = payload.get("type")
                if frame_type == "ping":
                    continue
                if frame_type == "typing":
                    # Ephemeral - relayed straight to Redis, never touches the DB/service.
                    await publish_event(
                        _CHANNEL_NAMESPACE,
                        community_id,
                        {
                            "type": "typing",
                            "community_id": str(community_id),
                            "user_id": str(user.id),
                            "is_typing": bool(payload.get("is_typing", True)),
                        },
                    )
                    continue
                if frame_type != "message":
                    continue
                try:
                    message_payload = CommunityMessageCreateDTO(
                        body=payload.get("body", ""),
                        reply_to_message_id=payload.get("reply_to_message_id"),
                        resource_reference_id=payload.get("resource_reference_id"),
                        attachment_storage_key=payload.get("attachment_storage_key"),
                        attachment_file_name=payload.get("attachment_file_name"),
                        attachment_mime_type=payload.get("attachment_mime_type"),
                        attachment_file_size_bytes=payload.get("attachment_file_size_bytes"),
                    )
                    await reader_service.post_message(community_id, message_payload, user)
                except (HTTPException, ValidationError) as exc:
                    detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
                    await websocket.send_text(json.dumps({"type": "error", "detail": detail}))

    async def subscriber() -> None:
        """Relays every event published to this community's Redis channel -
        messages and typing indicators alike - to this socket. If Redis isn't
        configured (local dev without it running), fall back to a no-op so the
        socket still accepts a connection, just without cross-connection fanout."""
        if cache_module.redis_client is None:
            await asyncio.Event().wait()
            return
        pubsub = cache_module.redis_client.pubsub()
        channel = channel_name(_CHANNEL_NAMESPACE, community_id)
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                await websocket.send_text(message["data"])
        finally:
            await pubsub.unsubscribe(channel)
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
