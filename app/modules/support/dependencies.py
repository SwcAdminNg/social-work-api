from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.support.staff import is_support_staff
from app.modules.user.entity import User


async def get_current_support_staff(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Admin-or-Support-Desk-member guard for the ticket queue/assign/status
    endpoints - see `app/modules/support/staff.py` for the "staff" definition."""
    if not await is_support_staff(current_user, db):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Support Desk access required")
    return current_user
