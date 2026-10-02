import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.course.content_service import CourseContentService
from app.modules.marking.dto import (
    ApproveMarkDTO,
    DisputeMarkDTO,
    EssayMarkReadDTO,
    ModerateMarkDTO,
    PublishMarksDTO,
    PublishMarksResultDTO,
)
from app.modules.marking.entity import LearnerResultStatusEnum
from app.modules.marking.service import MarkingService
from app.modules.user.entity import User

router = APIRouter(tags=["Governance - Essay Marking"], route_class=NoNullAPIRoute)


@router.get(
    "/essay-marks/{mark_id}",
    response_model=ApiResponse[EssayMarkReadDTO],
    summary="One mark with its moderation/approval trail and the actions the caller may take",
)
async def get_mark(
    mark_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[EssayMarkReadDTO]:
    service = MarkingService(db)
    mark = await service.get_mark(mark_id)
    return ApiResponse(message="Mark retrieved successfully", data=await service.get_dto(mark, current_user))


@router.post(
    "/essay-marks/{mark_id}/submit",
    response_model=ApiResponse[EssayMarkReadDTO],
    summary="Marker: send a draft (or returned) mark to moderation",
)
async def submit_mark(
    mark_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[EssayMarkReadDTO]:
    service = MarkingService(db)
    mark = await service.submit(mark_id, current_user)
    return ApiResponse(message="Sent to moderation", data=await service.get_dto(mark, current_user))


@router.post(
    "/essay-marks/{mark_id}/moderate",
    response_model=ApiResponse[EssayMarkReadDTO],
    summary="Moderator (not the marker): approve the mark, amend it, or return it for re-marking",
)
async def moderate_mark(
    mark_id: uuid.UUID,
    payload: ModerateMarkDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[EssayMarkReadDTO]:
    service = MarkingService(db)
    mark = await service.moderate(mark_id, payload, current_user)
    return ApiResponse(message="Moderation recorded", data=await service.get_dto(mark, current_user))


@router.post(
    "/essay-marks/{mark_id}/dispute",
    response_model=ApiResponse[EssayMarkReadDTO],
    summary="Marker: contest a moderated mark - a Course Lead / Lead Assessor settles it at approval",
)
async def dispute_mark(
    mark_id: uuid.UUID,
    payload: DisputeMarkDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[EssayMarkReadDTO]:
    service = MarkingService(db)
    mark = await service.dispute(mark_id, payload.note, current_user)
    return ApiResponse(message="Dispute recorded", data=await service.get_dto(mark, current_user))


@router.post(
    "/essay-marks/{mark_id}/approve",
    response_model=ApiResponse[EssayMarkReadDTO],
    summary="APPROVE_RESULTS holder (neither marker nor moderator): approve the moderated result, "
    "optionally publishing it to the learner",
)
async def approve_mark(
    mark_id: uuid.UUID,
    payload: ApproveMarkDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[EssayMarkReadDTO]:
    service = MarkingService(db)
    mark = await service.approve(mark_id, payload, current_user)
    return ApiResponse(message="Result approved", data=await service.get_dto(mark, current_user))


@router.post(
    "/courses/items/{item_id}/essay-marks/publish",
    response_model=ApiResponse[PublishMarksResultDTO],
    summary="Release approved results to learners - chosen marks or every approved mark on the item",
)
async def publish_marks(
    item_id: uuid.UUID,
    payload: PublishMarksDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PublishMarksResultDTO]:
    course, _, item = await CourseContentService(db).authorize_marking_item(item_id, current_user)
    result = await MarkingService(db).publish_for_item(
        course, item, payload.mark_ids, payload.all_approved, current_user
    )
    return ApiResponse(message=f"Published {result.published} result(s)", data=result)


@router.get(
    "/courses/items/{item_id}/essay-marks",
    response_model=ApiResponse[list[EssayMarkReadDTO]],
    summary="Marks on an essay item, optionally filtered by status (e.g. the moderation queue)",
)
async def list_item_marks(
    item_id: uuid.UUID,
    status: list[LearnerResultStatusEnum] | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[EssayMarkReadDTO]]:
    course, _, item = await CourseContentService(db).authorize_marking_item(item_id, current_user)
    data = await MarkingService(db).list_for_item(item, status, current_user, course)
    return ApiResponse(message="Marks retrieved successfully", data=data)


@router.get(
    "/courses/items/{item_id}/essay/submissions/{user_id}/marks",
    response_model=ApiResponse[list[EssayMarkReadDTO]],
    summary="Full marking history for one learner's essay (every attempt, every mark)",
)
async def mark_history(
    item_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[EssayMarkReadDTO]]:
    course, _, item = await CourseContentService(db).authorize_marking_item(item_id, current_user)
    data = await MarkingService(db).history(item, user_id, current_user, course)
    return ApiResponse(message="Mark history retrieved successfully", data=data)
