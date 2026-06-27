import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.pagination import PaginatedResponse, PaginationParams
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_admin_user
from app.modules.contact_us.dto import ContactUsCreateDTO, ContactUsFilterParams, ContactUsReadDTO
from app.modules.contact_us.service import ContactUsService
from app.modules.user.entity import User

router = APIRouter(prefix="/contact-us", tags=["Contact Us"], route_class=NoNullAPIRoute)


@router.post(
    "",
    response_model=ApiResponse[ContactUsReadDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Submit a contact us message",
)
async def submit_contact_us(
    payload: ContactUsCreateDTO, db: AsyncSession = Depends(get_db)
) -> ApiResponse[ContactUsReadDTO]:
    message = await ContactUsService(db).submit(payload)
    return ApiResponse(
        message="Your message has been submitted successfully",
        data=ContactUsReadDTO.model_validate(message),
    )


@router.get(
    "",
    response_model=PaginatedResponse[ContactUsReadDTO],
    summary="List all contact us messages (admin only)",
)
async def list_contact_us(
    pagination: PaginationParams = Depends(),
    filters: ContactUsFilterParams = Depends(),
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ContactUsReadDTO]:
    items, total = await ContactUsService(db).list(pagination, filters)
    return PaginatedResponse.create(
        items=[ContactUsReadDTO.model_validate(item) for item in items],
        total_items=total,
        params=pagination,
    )


@router.get(
    "/{id}",
    response_model=ApiResponse[ContactUsReadDTO],
    summary="Get a contact us message by id (admin only)",
)
async def get_contact_us(
    id: uuid.UUID,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ContactUsReadDTO]:
    message = await ContactUsService(db).get_by_id(id)
    return ApiResponse(message="Contact us message retrieved successfully", data=ContactUsReadDTO.model_validate(message))
