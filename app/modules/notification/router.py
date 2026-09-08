import asyncio
import uuid

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

import app.core.cache as cache_module
from app.common.api_route import NoNullAPIRoute
from app.common.pagination import PaginatedResponse, PaginationParams
from app.common.responses import ApiResponse
from app.core.database import AsyncSessionLocal, get_db
from app.modules.auth.dependencies import get_current_user, get_user_from_token
from app.modules.notification.dto import NotificationReadDTO, UnreadCountReadDTO
from app.modules.notification.service import NotificationService, notification_channel
from app.modules.user.entity import User
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/notifications", tags=["Notifications"], route_class=NoNullAPIRoute)


@router.get(
    "",
    response_model=PaginatedResponse[NotificationReadDTO],
    summary="List the current user's notifications, newest first",
)
async def list_notifications(
    pagination: PaginationParams = Depends(),
    unread_only: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[NotificationReadDTO]:
    items, total = await NotificationService(db).list_for_user(current_user, pagination, unread_only)
    return PaginatedResponse.create(
        items=[NotificationReadDTO.model_validate(n) for n in items], total_items=total, params=pagination
    )


@router.get(
    "/unread-count",
    response_model=ApiResponse[UnreadCountReadDTO],
    summary="Get the current user's unread notification count",
)
async def get_unread_count(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[UnreadCountReadDTO]:
    count = await NotificationService(db).get_unread_count(current_user)
    return ApiResponse(message="Unread count retrieved successfully", data=UnreadCountReadDTO(unread_count=count))


@router.patch(
    "/{notification_id}/read",
    response_model=ApiResponse[NotificationReadDTO],
    summary="Mark a single notification as read",
)
async def mark_notification_read(
    notification_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[NotificationReadDTO]:
    notification = await NotificationService(db).mark_read(notification_id, current_user)
    return ApiResponse(message="Notification marked as read", data=NotificationReadDTO.model_validate(notification))


@router.post(
    "/read-all",
    response_model=ApiResponse[None],
    summary="Mark every notification for the current user as read",
)
async def mark_all_read(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[None]:
    await NotificationService(db).mark_all_read(current_user)
    return ApiResponse(message="All notifications marked as read")


# ---------------------------------------------------------------------------
# WebSocket - realtime push
# ---------------------------------------------------------------------------


@router.websocket("/ws")
async def notifications_ws(websocket: WebSocket, token: str = Query(...)) -> None:
    async with AsyncSessionLocal() as db:
        user = await get_user_from_token(token, db)
        if user is None:
            await websocket.close(code=4401)
            return

    await websocket.accept()

    async def reader() -> None:
        # Client sends nothing meaningful besides keepalive pings - this socket is
        # push-only. Still drain incoming frames so a client ping doesn't pile up
        # or trip the connection, mirroring the ticket chat socket's reader loop.
        while True:
            await websocket.receive_text()

    async def subscriber() -> None:
        if cache_module.redis_client is None:
            await asyncio.Event().wait()
            return
        pubsub = cache_module.redis_client.pubsub()
        channel = notification_channel(user.id)
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
