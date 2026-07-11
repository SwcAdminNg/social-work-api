import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.pagination import PaginatedResponse, PaginationParams
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_admin_user, get_current_user, get_current_admin_or_instructor
from app.modules.course.review_dto import ReviewCreate, ReviewHideDTO, ReviewRead, ReviewAdminRead, ReviewReplyDTO, ReviewUpdate
from app.modules.course.review_service import CourseReviewService
from app.modules.user.entity import User

router = APIRouter(prefix="/courses", tags=["Course Reviews"], route_class=NoNullAPIRoute)


@router.get(
    "/reviews/all",
    response_model=PaginatedResponse[ReviewAdminRead],
    summary="List all reviews across all courses (admin only)",
)
async def list_all_reviews_for_admin(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ReviewAdminRead]:
    service = CourseReviewService(db)
    items, total = await service.list_all_reviews_for_admin(pagination, current_user)
    
    return PaginatedResponse.create(
        items=[ReviewAdminRead.model_validate(r) for r in items],
        total_items=total,
        params=pagination,
    )


@router.post(
    "/{course_id}/reviews",
    response_model=ApiResponse[ReviewRead],
    status_code=status.HTTP_201_CREATED,
    summary="Leave a review for a course",
)
async def create_review(
    course_id: uuid.UUID,
    payload: ReviewCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ReviewRead]:
    service = CourseReviewService(db)
    review = await service.create_review(course_id, payload, current_user)
    # The review.user might not be loaded, let's load it manually for the response
    review.user = current_user
    return ApiResponse(
        message="Review submitted successfully", 
        data=ReviewRead.model_validate(review)
    )


@router.get(
    "/{course_id}/reviews/me",
    response_model=ApiResponse[ReviewRead],
    summary="Get the current user's review for a course",
)
async def get_my_review(
    course_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ReviewRead]:
    service = CourseReviewService(db)
    review = await service.get_my_review(course_id, current_user)
    review.user = current_user
    return ApiResponse(
        message="Review retrieved successfully", 
        data=ReviewRead.model_validate(review)
    )


@router.get(
    "/{course_id}/reviews",
    response_model=PaginatedResponse[ReviewRead],
    summary="List paginated reviews for a course (public)",
)
async def list_course_reviews(
    course_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ReviewRead]:
    cache_key = f"reviews:course_{course_id}:page_{pagination.page}:size_{pagination.page_size}"
    from app.core.cache import get_cache, set_cache
    cached_data = await get_cache(cache_key)
    if cached_data:
        items = [ReviewRead(**r) for r in cached_data['items']]
        return PaginatedResponse.create(
            items=items,
            total_items=cached_data['total'],
            params=pagination,
        )

    service = CourseReviewService(db)
    items, total = await service.list_course_reviews(course_id, pagination)
    
    data = PaginatedResponse.create(
        items=[ReviewRead.model_validate(r) for r in items],
        total_items=total,
        params=pagination,
    )
    
    serializable_data = [item.model_dump(mode='json') for item in data.data]
    await set_cache(cache_key, {'items': serializable_data, 'total': total}, expire=600)
    
    return data


@router.put(
    "/reviews/{review_id}",
    response_model=ApiResponse[ReviewRead],
    summary="Update a review",
)
async def update_review(
    review_id: uuid.UUID,
    payload: ReviewUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ReviewRead]:
    service = CourseReviewService(db)
    review = await service.update_review(review_id, payload, current_user)
    review.user = current_user
    return ApiResponse(
        message="Review updated successfully", 
        data=ReviewRead.model_validate(review)
    )


@router.delete(
    "/reviews/{review_id}",
    response_model=ApiResponse[None],
    summary="Delete a review",
)
async def delete_review(
    review_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    service = CourseReviewService(db)
    await service.delete_review(review_id, current_user)
    return ApiResponse(message="Review deleted successfully")


@router.patch(
    "/reviews/{review_id}/reply",
    response_model=ApiResponse[ReviewRead],
    summary="Instructor or admin reply to a review",
)
async def reply_to_review(
    review_id: uuid.UUID,
    payload: ReviewReplyDTO,
    current_user: User = Depends(get_current_admin_or_instructor),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ReviewRead]:
    service = CourseReviewService(db)
    review = await service.reply_to_review(review_id, payload, current_user)
    return ApiResponse(
        message="Reply submitted successfully", 
        data=ReviewRead.model_validate(review)
    )


@router.patch(
    "/reviews/{review_id}/hide",
    response_model=ApiResponse[ReviewRead],
    summary="Admin hide or unhide a review (e.g. for hate speech)",
)
async def hide_review(
    review_id: uuid.UUID,
    payload: ReviewHideDTO,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ReviewRead]:
    service = CourseReviewService(db)
    review = await service.hide_review(review_id, payload, current_user)
    return ApiResponse(
        message="Review visibility updated successfully", 
        data=ReviewRead.model_validate(review)
    )
