import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.community.entity import Community, CommunityMembership, CommunityTypeEnum
from app.modules.course.access_entity import UserCourseAccess
from app.modules.course.entity import Course
from app.modules.course.instructor_entity import CourseInstructor
from app.modules.user.entity import User, UserTypeEnum

"""Single dispatch point for "is user X a member of community Y" / "who are
community Y's members", used by router guards, the service layer, and the
WebSocket handshake - callers never need to know which table (if any) backs a
given community type."""


async def _is_course_instructor_or_enrolled(db: AsyncSession, course_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    enrolled_stmt = select(UserCourseAccess.id).where(
        UserCourseAccess.course_id == course_id, UserCourseAccess.user_id == user_id
    )
    if (await db.execute(enrolled_stmt)).scalar_one_or_none() is not None:
        return True

    owner_stmt = select(Course.id).where(Course.id == course_id, Course.instructor_id == user_id)
    if (await db.execute(owner_stmt)).scalar_one_or_none() is not None:
        return True

    co_instructor_stmt = select(CourseInstructor.id).where(
        CourseInstructor.course_id == course_id, CourseInstructor.user_id == user_id
    )
    return (await db.execute(co_instructor_stmt)).scalar_one_or_none() is not None


async def _has_membership_row(db: AsyncSession, community_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    stmt = select(CommunityMembership.id).where(
        CommunityMembership.deleted_at.is_(None),
        CommunityMembership.community_id == community_id,
        CommunityMembership.user_id == user_id,
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def is_member(db: AsyncSession, community: Community, user: User) -> bool:
    if user.user_type == UserTypeEnum.ADMIN:
        return True

    if community.type in (CommunityTypeEnum.GENERAL, CommunityTypeEnum.HELP):
        return user.is_active and not user.is_suspended

    if community.type == CommunityTypeEnum.COURSE:
        if community.course_id is None:
            return False
        return await _is_course_instructor_or_enrolled(db, community.course_id, user.id)

    if community.type == CommunityTypeEnum.CUSTOM:
        return await _has_membership_row(db, community.id, user.id)

    return False


async def list_member_ids(db: AsyncSession, community: Community) -> list[uuid.UUID]:
    """Actual members - deliberately does NOT add every admin to COURSE/CUSTOM
    rosters just because `is_member` grants admins blanket access to every
    community. That blanket access is an authorization bypass, not membership:
    an admin who never enrolled/was added shouldn't inflate a roster, a member
    count, or the "who's online in this room" list."""
    if community.type in (CommunityTypeEnum.GENERAL, CommunityTypeEnum.HELP):
        stmt = select(User.id).where(User.deleted_at.is_(None), User.is_active.is_(True))
        return list((await db.execute(stmt)).scalars().all())

    if community.type == CommunityTypeEnum.COURSE:
        if community.course_id is None:
            return []
        return await list_course_member_ids(db, community.course_id)

    if community.type == CommunityTypeEnum.CUSTOM:
        stmt = select(CommunityMembership.user_id).where(
            CommunityMembership.deleted_at.is_(None), CommunityMembership.community_id == community.id
        )
        return list((await db.execute(stmt)).scalars().all())

    return []


async def list_course_member_ids(db: AsyncSession, course_id: uuid.UUID) -> list[uuid.UUID]:
    """Every current enrollee + instructor (owner and co-instructors) of a course -
    deliberately excludes admins (unlike `list_member_ids`), since this is also
    used to build a CUSTOM community's one-time course-enrollee snapshot and an
    admin didn't "enroll" into that snapshot just by being an admin."""
    enrolled_stmt = select(UserCourseAccess.user_id).where(UserCourseAccess.course_id == course_id)
    owner_stmt = select(Course.instructor_id).where(Course.id == course_id)
    co_instructor_stmt = select(CourseInstructor.user_id).where(
        CourseInstructor.course_id == course_id, CourseInstructor.user_id.is_not(None)
    )

    member_ids: set[uuid.UUID] = set((await db.execute(enrolled_stmt)).scalars().all())
    member_ids.update((await db.execute(owner_stmt)).scalars().all())
    member_ids.update((await db.execute(co_instructor_stmt)).scalars().all())
    return list(member_ids)
