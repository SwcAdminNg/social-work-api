import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.pagination import PaginatedResponse, PaginationParams
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_admin_user, get_current_user
from app.modules.coupon.dto import (
    CouponCreateDTO,
    CouponReadDTO,
    CouponUpdateDTO,
    CouponValidateRequest,
    CouponValidateResponse,
)
from app.modules.coupon.service import CouponService
from app.modules.course.repository import CourseRepository
from app.modules.user.entity import User

router = APIRouter(prefix="/coupons", tags=["Coupons"], route_class=NoNullAPIRoute)


# ---------------------------------------------------------------------------
# Admin management
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=ApiResponse[CouponReadDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Create a coupon (Admin only)",
)
async def create_coupon(
    payload: CouponCreateDTO,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CouponReadDTO]:
    coupon = await CouponService(db).create(payload)
    return ApiResponse(message="Coupon created successfully", data=CouponReadDTO.model_validate(coupon))


@router.get(
    "",
    response_model=PaginatedResponse[CouponReadDTO],
    summary="List all coupons (Admin only)",
)
async def list_coupons(
    pagination: PaginationParams = Depends(),
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[CouponReadDTO]:
    items, total = await CouponService(db).list_all(pagination)
    return PaginatedResponse.create(
        items=[CouponReadDTO.model_validate(c) for c in items], total_items=total, params=pagination
    )


@router.get(
    "/{coupon_id}",
    response_model=ApiResponse[CouponReadDTO],
    summary="Get a coupon by id (Admin only)",
)
async def get_coupon(
    coupon_id: uuid.UUID,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CouponReadDTO]:
    coupon = await CouponService(db).get_by_id(coupon_id)
    return ApiResponse(message="Coupon retrieved successfully", data=CouponReadDTO.model_validate(coupon))


@router.patch(
    "/{coupon_id}",
    response_model=ApiResponse[CouponReadDTO],
    summary="Update a coupon (Admin only)",
)
async def update_coupon(
    coupon_id: uuid.UUID,
    payload: CouponUpdateDTO,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CouponReadDTO]:
    coupon = await CouponService(db).update(coupon_id, payload)
    return ApiResponse(message="Coupon updated successfully", data=CouponReadDTO.model_validate(coupon))


@router.delete(
    "/{coupon_id}",
    response_model=ApiResponse[None],
    summary="Delete a coupon (Admin only)",
)
async def delete_coupon(
    coupon_id: uuid.UUID,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await CouponService(db).delete(coupon_id)
    return ApiResponse(message="Coupon deleted successfully")


# ---------------------------------------------------------------------------
# Customer-facing preview
# ---------------------------------------------------------------------------


@router.post(
    "/validate",
    response_model=ApiResponse[CouponValidateResponse],
    summary="Preview a coupon's discount against a set of courses (defaults to the caller's current cart)",
)
async def validate_coupon(
    payload: CouponValidateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CouponValidateResponse]:
    course_ids = payload.course_ids
    if course_ids is None:
        from app.modules.cart.repository import CartRepository

        cart_items = await CartRepository(db).list_for_user(current_user.id)
        course_ids = [item.course_id for item in cart_items]

    courses = await CourseRepository(db).get_many_by_ids(course_ids)
    if not courses:
        return ApiResponse(
            message="No priceable items to apply this coupon to",
            data=CouponValidateResponse(
                valid=False, code=payload.code, subtotal_amount=0, discount_amount=0, total_amount=0,
                message="Your cart is empty" if payload.course_ids is None else "No matching courses found",
            ),
        )

    application = await CouponService(db).validate_and_compute(payload.code, current_user, list(courses))
    data = CouponValidateResponse(
        code=application.coupon.code,
        subtotal_amount=application.subtotal_amount,
        discount_amount=application.discount_amount,
        total_amount=application.total_amount,
    )
    return ApiResponse(message="Coupon applied", data=data)
