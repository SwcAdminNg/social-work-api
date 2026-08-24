from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.group.repository import GroupMembershipRepository, GroupRepository
from app.modules.user.entity import User, UserTypeEnum

SUPPORT_DESK_GROUP_NAME = "Support Desk"


async def is_support_staff(user: User, session: AsyncSession) -> bool:
    """True for an ADMIN (always staff), or any active member of the "Support
    Desk" group (e.g. an INSTRUCTOR who has been added to it) - see
    GROUPS_ADMIN_API.md. This is the single definition of "staff" for ticket
    access, message sender_type, and the ticket queue/assign/status endpoints."""
    if user.user_type == UserTypeEnum.ADMIN:
        return True

    group = await GroupRepository(session).get_by_name(SUPPORT_DESK_GROUP_NAME)
    if group is None:
        return False
    membership = await GroupMembershipRepository(session).get_membership(group.id, user.id)
    return membership is not None
