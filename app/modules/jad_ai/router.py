import uuid

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.jad_ai.dto import JadAskDTO, JadFeedbackDTO, JadStateDTO
from app.modules.jad_ai.service import JadService
from app.modules.user.entity import User

router = APIRouter(prefix="/jad-ai", tags=["JAD AI"], route_class=NoNullAPIRoute)


@router.get(
    "/courses/{course_id}/items/{item_id}",
    response_model=ApiResponse[JadStateDTO],
    summary="JAD AI on a lesson: availability, starter questions and the learner's chat so far",
)
async def get_jad_state(
    course_id: uuid.UUID,
    item_id: uuid.UUID,
    background: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[JadStateDTO]:
    state, needs_warmup = await JadService(db).get_state(current_user, course_id, item_id)
    if needs_warmup:
        background.add_task(JadService.warm_up, item_id)
    return ApiResponse(data=state)


@router.post(
    "/courses/{course_id}/items/{item_id}/messages",
    summary="Ask JAD AI about a lesson. Streams Server-Sent Events: start {cached}, "
    "delta {t} (append), replace {t} (swap the whole answer), done {message_id, suggestions, cached}, "
    "error {message}",
)
async def ask_jad(
    course_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: JadAskDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    service = JadService(db)
    turn = await service.prepare_turn(current_user, course_id, item_id, payload)
    return StreamingResponse(
        service.stream_turn(turn),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.delete(
    "/courses/{course_id}/items/{item_id}/messages",
    response_model=ApiResponse[None],
    summary="Start a new chat with JAD AI on this lesson",
)
async def clear_jad_chat(
    course_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await JadService(db).clear(current_user, course_id, item_id)
    return ApiResponse(message="New chat started")


@router.post(
    "/messages/{message_id}/feedback",
    response_model=ApiResponse[None],
    summary="Rate a JAD AI answer. A thumbs-down also retires it from the shared answer cache",
)
async def rate_jad_answer(
    message_id: uuid.UUID,
    payload: JadFeedbackDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await JadService(db).feedback(current_user, message_id, payload.helpful)
    return ApiResponse(message="Thanks for the feedback")
