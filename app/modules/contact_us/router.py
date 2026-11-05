import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.pagination import PaginatedResponse, PaginationParams
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_admin_user
from app.core.config import settings
from app.modules.contact_us.dto import ContactUsCreateDTO, ContactUsFilterParams, ContactUsReadDTO
from app.modules.contact_us.rate_limit import contact_limiter
from app.modules.contact_us.service import ContactUsService, send_enquiry_notification
from app.modules.user.entity import User

router = APIRouter(prefix="/contact-us", tags=["Contact Us"], route_class=NoNullAPIRoute)


@router.post(
    "",
    response_model=ApiResponse[ContactUsReadDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Submit a contact us message",
)
async def submit_contact_us(
    payload: ContactUsCreateDTO,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ContactUsReadDTO]:
    if payload.is_spam:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "We could not accept this message.")

    window = settings.contact_rate_limit_window_seconds
    ip_ok = contact_limiter.hit(f"ip:{_client_ip(request)}", settings.contact_rate_limit_per_ip, window)
    email_ok = contact_limiter.hit(
        f"email:{payload.email.lower()}", settings.contact_rate_limit_per_email, window
    )
    if not (ip_ok and email_ok):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "You have sent several messages in a short time. Please wait a few minutes and try again.",
            headers={"Retry-After": str(window)},
        )

    message = await ContactUsService(db).submit(payload)
    data = ContactUsReadDTO.model_validate(message)
    if settings.contact_notify_email:
        background_tasks.add_task(send_enquiry_notification, data)
    return ApiResponse(message="Your message has been submitted successfully", data=data)


def _client_ip(request: Request) -> str:
    """The visitor's address. The public sites submit through their own server,
    which passes the visitor's address on as the first X-Forwarded-For entry."""
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    if first:
        return first[:64]
    return request.client.host if request.client else "unknown"


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
