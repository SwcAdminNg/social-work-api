from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses import ApiResponse
from app.core.database import get_db

router = APIRouter(prefix="/health", tags=["Health"])


class HealthStatus(BaseModel):
    status: str
    database: str


@router.get("", response_model=ApiResponse[HealthStatus], summary="Health check")
async def check_health(db: AsyncSession = Depends(get_db)) -> ApiResponse[HealthStatus]:
    """Liveness/readiness probe. Verifies the API process is up and that it can
    reach the Postgres database."""
    try:
        await db.execute(text("SELECT 1"))
        db_status = "up"
    except Exception:
        db_status = "down"

    overall = "ok" if db_status == "up" else "degraded"
    return ApiResponse(
        message="Health check completed",
        data=HealthStatus(status=overall, database=db_status),
    )
