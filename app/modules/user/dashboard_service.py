import uuid
from datetime import datetime, timezone
from typing import Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.modules.cart.repository import CartRepository
from app.modules.certificate.service import CertificateService
from app.modules.community.service import CommunityService
from app.modules.course.access_entity import UserCourseAccess
from app.modules.course.bookmark_entity import CourseBookmark
from app.modules.course.review_entity import CourseReview
from app.modules.learning.entity import QuizAttempt, UserCourseProgress
from app.modules.learning.repository import LearningRepository
from app.modules.learning.service import LearningService
from app.modules.notification.repository import NotificationRepository
from app.modules.payment.repository import PaymentRepository
from app.modules.payment.schema import CurrentSubscriptionResponse, SubscriptionPlanResponse
from app.modules.payment.service import PaymentService
from app.modules.support.repository import SupportTicketRepository
from app.modules.user.activity_entity import ActivityLog
from app.modules.user.dashboard_dto import ActivityLogDTO, ContinueLearningItemDTO, DashboardOverviewDTO, UserStatsDTO
from app.modules.user.entity import User


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

    async def get_overview(self, user: User, limit: int = 5) -> DashboardOverviewDTO:
        """Composes every "above the fold" dashboard section in one call. Each
        section is also independently available as its own (paginated) endpoint
        for a "view all" - this just avoids the frontend firing off ~8 parallel
        requests on every dashboard load."""
        user_id = user.id

        stats = await self.get_user_stats(user_id)

        # Continue learning: most-recently-accessed enrolled courses, excluding
        # ones already completed (those belong in the certificates section
        # instead). Over-fetch a bit since completed courses get filtered out.
        rows, _ = await LearningRepository(self.db).get_enrolled_courses_with_progress(
            user_id, PaginationParams(page=1, page_size=limit * 3)
        )
        continue_learning = [
            ContinueLearningItemDTO(
                course_id=course.id,
                title=course.title,
                slug=course.slug,
                thumbnail_url=course.thumbnail_url,
                progress_percent=progress.progress_percent,
                last_accessed_at=progress.last_accessed_at,
            )
            for course, progress in rows
            if not progress.is_completed
        ][:limit]

        upcoming_live_sessions, _ = await LearningService(self.db).list_user_live_sessions(
            user_id, PaginationParams(page=1, page_size=limit), start_date=datetime.now(timezone.utc)
        )

        recent_certificates, _ = await CertificateService(self.db).list_my_certificates(
            user, PaginationParams(page=1, page_size=limit)
        )

        recent_activity_items, _ = await self.list_recent_activity(user_id, PaginationParams(page=1, page_size=limit))

        unread_notifications_count = await NotificationRepository(self.db).count_unread(user_id)
        unread_community = await CommunityService(self.db).get_unread_count(user)
        open_support_tickets_count = await SupportTicketRepository(self.db).count_open_for_user(user_id)
        cart_item_count = len(await CartRepository(self.db).list_for_user(user_id))

        subscription = None
        sub = await PaymentService(self.db).get_current_subscription(user_id)
        if sub is not None:
            plan = await PaymentRepository(self.db).get_plan_by_id(sub.plan_id)
            subscription = CurrentSubscriptionResponse(
                id=sub.id,
                plan_id=sub.plan_id,
                start_date=sub.start_date,
                end_date=sub.end_date,
                is_active=sub.is_active,
                auto_renew=sub.auto_renew,
                pending_plan_id=sub.pending_plan_id,
                plan=SubscriptionPlanResponse.model_validate(plan, from_attributes=True) if plan else None,
            )

        return DashboardOverviewDTO(
            stats=stats,
            continue_learning=continue_learning,
            upcoming_live_sessions=upcoming_live_sessions,
            recent_certificates=recent_certificates,
            recent_activity=[ActivityLogDTO.model_validate(a) for a in recent_activity_items],
            unread_notifications_count=unread_notifications_count,
            unread_community_messages_count=unread_community.total_unread,
            open_support_tickets_count=open_support_tickets_count,
            cart_item_count=cart_item_count,
            subscription=subscription,
        )
