import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.pagination import PaginatedResponse, PaginationParams
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_admin_user
from app.modules.course.repository import CourseRepository
from app.modules.course.dto import CourseReadDTO
from app.modules.payment.repository import PaymentRepository
from app.modules.payment.schema import SavedCardResponse, TransactionReadDTO
from app.modules.customer_support.schema import CourseTransactionReadDTO
from app.modules.user.dto import UserReadDTO
from app.modules.user.entity import User

router = APIRouter(prefix="/customer-support", tags=["Customer Support"], route_class=NoNullAPIRoute)


@router.get(
    "/users/{user_id}/transactions",
    response_model=PaginatedResponse[TransactionReadDTO],
    summary="Get user's transaction history",
)
async def get_user_transactions(
    user_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[TransactionReadDTO]:
    items, total = await PaymentRepository(db).list_user_transactions(user_id, pagination)
    
    result_items = []
    for transaction, user in items:
        dto = TransactionReadDTO(
            **TransactionReadDTO.model_validate(transaction, from_attributes=True).model_dump(exclude={'user'}),
            user=UserReadDTO.model_validate(user, from_attributes=True)
        )
        result_items.append(dto)
        
    return PaginatedResponse.create(
        items=result_items,
        total_items=total,
        params=pagination,
    )


@router.get(
    "/users/{user_id}/courses",
    response_model=PaginatedResponse[CourseReadDTO],
    summary="Get user's enrolled courses",
)
async def get_user_courses(
    user_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[CourseReadDTO]:
    items, total = await CourseRepository(db).list_enrolled(user_id, pagination)
    return PaginatedResponse.create(
        items=[CourseReadDTO.model_validate(item) for item in items],
        total_items=total,
        params=pagination,
    )


@router.get(
    "/users/{user_id}/cards",
    response_model=ApiResponse[list[SavedCardResponse]],
    summary="Get user's saved cards",
)
async def get_user_cards(
    user_id: uuid.UUID,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[SavedCardResponse]]:
    cards = await PaymentRepository(db).list_user_saved_cards(user_id)
    data = [SavedCardResponse.model_validate(card, from_attributes=True) for card in cards]
    return ApiResponse(message="Saved cards retrieved successfully", data=data)


@router.get(
    "/courses/{course_id}/transactions",
    response_model=PaginatedResponse[CourseTransactionReadDTO],
    summary="Get all transactions for a specific course (includes user and card type)",
)
async def get_course_transactions(
    course_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[CourseTransactionReadDTO]:
    items, total = await PaymentRepository(db).list_course_transactions_with_users(course_id, pagination)
    
    result_items = []
    for transaction, user in items:
        # Extract card type from gateway_response if available
        card_type = None
        if transaction.gateway_response:
            auth_data = transaction.gateway_response.get("authorization")
            if auth_data:
                card_type = auth_data.get("card_type")
        
        dto = CourseTransactionReadDTO(
            **TransactionReadDTO.model_validate(transaction, from_attributes=True).model_dump(),
            user=UserReadDTO.model_validate(user, from_attributes=True),
            card_type=card_type
        )
        result_items.append(dto)

    return PaginatedResponse.create(
        items=result_items,
        total_items=total,
        params=pagination,
    )
