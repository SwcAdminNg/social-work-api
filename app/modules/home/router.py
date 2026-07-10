from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.home.dto import HomeStatsDTO
from app.modules.home.service import HomeService

router = APIRouter(prefix="/home", tags=["Home"], route_class=NoNullAPIRoute)


@router.get("/stats", response_model=ApiResponse[HomeStatsDTO], summary="Get home stats")
async def get_home_stats(db: AsyncSession = Depends(get_db)) -> ApiResponse[HomeStatsDTO]:
    stats = await HomeService(db).get_stats()
    return ApiResponse(data=stats, message="Home stats retrieved successfully")
