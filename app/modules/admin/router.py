from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.admin.dto import AcceptAdminInviteRequestDTO, AdminInviteResponseDTO, InviteAdminRequestDTO
from app.modules.admin.service import AdminService
from app.modules.auth.dependencies import get_current_admin_user
from app.modules.auth.dto import MessageDTO
from app.modules.user.dto import UserReadDTO
from app.modules.user.entity import User

router = APIRouter(prefix="/admin", tags=["Admin Users"], route_class=NoNullAPIRoute)


@router.post(
    "/invite",
    response_model=ApiResponse[AdminInviteResponseDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Invite a new admin user (admin only)",
)
async def invite_admin(
    payload: InviteAdminRequestDTO,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[AdminInviteResponseDTO]:
    user = await AdminService(db).invite_admin(current_admin, payload)
    return ApiResponse(
        message="Invite sent successfully",
        data=AdminInviteResponseDTO(user=UserReadDTO.model_validate(user)),
    )


@router.post(
    "/accept-invite",
    response_model=ApiResponse[MessageDTO],
    summary="Accept an admin invite by setting a password",
)
async def accept_admin_invite(
    payload: AcceptAdminInviteRequestDTO, db: AsyncSession = Depends(get_db)
) -> ApiResponse[MessageDTO]:
    await AdminService(db).accept_invite(payload)
    return ApiResponse(
        message="Invite accepted successfully",
        data=MessageDTO(message="Your password has been set. You can now log in."),
    )

from app.common.pagination import PaginatedResponse, PaginationParams
from app.modules.payment.schema import TransactionReadDTO
from app.modules.payment.repository import PaymentRepository

@router.get(
    "/payments",
    response_model=PaginatedResponse[TransactionReadDTO],
    summary="List all payments/transactions (admin only)",
)
async def list_payments(
    pagination: PaginationParams = Depends(),
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[TransactionReadDTO]:
    items, total = await PaymentRepository(db).list_transactions(pagination)
    return PaginatedResponse.create(
        items=[TransactionReadDTO.model_validate(item, from_attributes=True) for item in items],
        total_items=total,
        params=pagination,
    )
