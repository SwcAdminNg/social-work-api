from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.user.entity import User, UserTypeEnum
from app.modules.course.entity import Course
from app.modules.learning.entity import UserCourseProgress
from app.modules.home.dto import HomeStatsDTO


class HomeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_stats(self) -> HomeStatsDTO:
        # Total number of students
        stmt_students = select(func.count()).select_from(User).where(User.user_type == UserTypeEnum.USER)
        total_students = (await self.session.execute(stmt_students)).scalar() or 0

        # Number of published courses
        stmt_courses = select(func.count()).select_from(Course).where(Course.is_published.is_(True))
        total_courses = (await self.session.execute(stmt_courses)).scalar() or 0

        # Completion rate
        stmt_completion = select(func.avg(UserCourseProgress.progress_percent))
        avg_completion = (await self.session.execute(stmt_completion)).scalar() or 0.0

        return HomeStatsDTO(
            total_number_of_students=total_students,
            number_of_published_courses=total_courses,
            completion_rate_of_course_by_enrolled_users=float(avg_completion)
        )
