import uuid
from typing import Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.modules.course.access_entity import UserCourseAccess
from app.modules.course.bookmark_entity import CourseBookmark
from app.modules.course.review_entity import CourseReview
from app.modules.learning.entity import QuizAttempt, UserCourseProgress
from app.modules.user.activity_entity import ActivityLog
from app.modules.user.dashboard_dto import UserStatsDTO


class DashboardService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_stats(self, user_id: uuid.UUID) -> UserStatsDTO:
        # 1. Total Courses Enrolled
        enrolled_stmt = select(func.count()).select_from(UserCourseAccess).where(
            UserCourseAccess.user_id == user_id
        )
        total_courses_enrolled = (await self.db.execute(enrolled_stmt)).scalar_one()

        # 2. Quizzes Attempted
        quizzes_stmt = select(func.count()).select_from(QuizAttempt).where(
            QuizAttempt.user_id == user_id
        )
        quizzes_attempted = (await self.db.execute(quizzes_stmt)).scalar_one()

        # 3. Completion rate (average progress_percent)
        completion_rate_stmt = select(func.avg(UserCourseProgress.progress_percent)).where(
            UserCourseProgress.user_id == user_id
        )
        completion_rate_val = (await self.db.execute(completion_rate_stmt)).scalar_one()
        completion_rate = float(completion_rate_val) if completion_rate_val is not None else 0.0

        # 4. Total Reviews
        reviews_stmt = select(func.count()).select_from(CourseReview).where(
            CourseReview.user_id == user_id,
            CourseReview.is_hidden == False
        )
        total_reviews = (await self.db.execute(reviews_stmt)).scalar_one()

        # 5. In-process Courses
        in_process_stmt = select(func.count()).select_from(UserCourseProgress).where(
            UserCourseProgress.user_id == user_id,
            UserCourseProgress.progress_percent > 0,
            UserCourseProgress.is_completed == False
        )
        in_process_courses = (await self.db.execute(in_process_stmt)).scalar_one()

        # 6. Completed Courses
        completed_stmt = select(func.count()).select_from(UserCourseProgress).where(
            UserCourseProgress.user_id == user_id,
            UserCourseProgress.is_completed == True
        )
        completed_courses = (await self.db.execute(completed_stmt)).scalar_one()

        # 7. Not-started Courses: enrolled but with no progress made yet
        not_started_courses = max(0, total_courses_enrolled - in_process_courses - completed_courses)

        # 8. Bookmarked Courses
        bookmarked_stmt = select(func.count()).select_from(CourseBookmark).where(
            CourseBookmark.user_id == user_id
        )
        bookmarked_courses = (await self.db.execute(bookmarked_stmt)).scalar_one()

        return UserStatsDTO(
            total_courses_enrolled=total_courses_enrolled,
            quizzes_attempted=quizzes_attempted,
            completion_rate=completion_rate,
            total_reviews=total_reviews,
            in_process_courses=in_process_courses,
            completed_courses=completed_courses,
            not_started_courses=not_started_courses,
            bookmarked_courses=bookmarked_courses,
        )

    async def list_recent_activity(
        self, user_id: uuid.UUID, pagination: PaginationParams
    ) -> Tuple[Sequence[ActivityLog], int]:
        base_stmt = select(ActivityLog).where(ActivityLog.user_id == user_id)
        
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()

        stmt = (
            base_stmt
            .order_by(ActivityLog.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
        items = (await self.db.execute(stmt)).scalars().all()

        return items, total
