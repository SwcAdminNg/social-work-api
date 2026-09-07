from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses import ApiResponse
from app.core.config import settings
from app.core.database import get_db
from app.modules.course.live_session_service import LiveSessionService

router = APIRouter(prefix="/webhooks/daily", tags=["Webhooks"])


@router.post(
    "/events",
    response_model=ApiResponse[None],
    summary="daily.co room/recording event callback (configure the URL with ?secret=... "
    "in the daily.co dashboard)",
    include_in_schema=False,
)
async def daily_events(
    request: Request, secret: str, db: AsyncSession = Depends(get_db)
) -> ApiResponse[None]:
    if secret != settings.daily_webhook_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook secret")

    payload = await request.json()
    event_type = payload.get("type")
    event_payload = payload.get("payload", {})
    if event_type:
        await LiveSessionService(db).handle_daily_webhook(event_type, event_payload)

    return ApiResponse(message="Webhook processed successfully")
