import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.cart.dto import AddCartItemRequest, CartReadDTO, CheckoutCartRequest
from app.modules.cart.service import CartService
from app.modules.payment.schema import InitializePaymentResponse
from app.modules.payment.service import PaymentService
from app.modules.user.entity import User

router = APIRouter(prefix="/cart", tags=["Cart"], route_class=NoNullAPIRoute)


@router.get("", response_model=ApiResponse[CartReadDTO], summary="Get the current user's cart")
async def get_cart(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CartReadDTO]:
    data = await CartService(db).get_cart(current_user)
    return ApiResponse(message="Cart retrieved successfully", data=data)


@router.post("/items", response_model=ApiResponse[CartReadDTO], summary="Add a course to the cart")
async def add_cart_item(
    payload: AddCartItemRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CartReadDTO]:
    data = await CartService(db).add_item(current_user, payload.course_id)
    return ApiResponse(message="Course added to cart", data=data)


@router.delete("/items/{course_id}", response_model=ApiResponse[CartReadDTO], summary="Remove a course from the cart")
async def remove_cart_item(
    course_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CartReadDTO]:
    data = await CartService(db).remove_item(current_user, course_id)
    return ApiResponse(message="Course removed from cart", data=data)


@router.delete("", response_model=ApiResponse[None], summary="Clear the current user's cart")
async def clear_cart(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await CartService(db).clear(current_user)
    return ApiResponse(message="Cart cleared")


@router.post(
    "/checkout",
    response_model=ApiResponse[InitializePaymentResponse],
    summary="Checkout the current user's cart and initialize payment for all items",
)
async def checkout_cart(
    payload: CheckoutCartRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[InitializePaymentResponse]:
    data = await PaymentService(db).checkout_cart(
        current_user, payload.coupon_code, payload.gateway, payload.save_card
    )
    return ApiResponse(message="Checkout initialized", data=InitializePaymentResponse(**data))
