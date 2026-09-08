from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.pagination import PaginatedResponse, PaginationParams
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.user.dashboard_dto import ActivityLogDTO, DashboardOverviewDTO, UserStatsDTO
from app.modules.user.dashboard_service import DashboardService
from app.modules.user.entity import User

router = APIRouter(prefix="/users/me/dashboard", tags=["User Dashboard"], route_class=NoNullAPIRoute)


@router.get(
    "/overview",
    response_model=ApiResponse[DashboardOverviewDTO],
    summary="Get everything the dashboard homepage needs in one call: stats, continue-learning, "
    "upcoming live sessions, recent certificates, recent activity, and unread/open counts",
)
async def get_dashboard_overview(
    limit: int = 5,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[DashboardOverviewDTO]:
    service = DashboardService(db)
    overview = await service.get_overview(current_user, limit=limit)
    return ApiResponse(message="Dashboard overview retrieved successfully", data=overview)


@router.get(
    "/stats",
    response_model=ApiResponse[UserStatsDTO],
    summary="Get aggregated statistics for the current user",
)
async def get_user_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[UserStatsDTO]:
    service = DashboardService(db)
    stats = await service.get_user_stats(current_user.id)
    return ApiResponse(
        message="User statistics retrieved successfully",
        data=stats
    )


@router.get(
    "/activity",
    response_model=PaginatedResponse[ActivityLogDTO],
    summary="List paginated recent activity for the current user",
)
async def list_recent_activity(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ActivityLogDTO]:
    service = DashboardService(db)
    items, total = await service.list_recent_activity(current_user.id, pagination)
    
    return PaginatedResponse.create(
        items=[ActivityLogDTO.model_validate(item) for item in items],
        total_items=total,
        params=pagination,
    )
