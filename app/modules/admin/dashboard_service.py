from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.modules.admin.dashboard_dto import (
    AdminContactStatsDTO,
    AdminCourseStatsDTO,
    AdminDashboardOverviewDTO,
    AdminReviewStatsDTO,
    AdminRevenueStatsDTO,
    AdminSupportStatsDTO,
    AdminUserStatsDTO,
    RecentSignupDTO,
    RecentTransactionDTO,
    TopEnrolledCourseDTO,
)
from app.modules.certificate.repository import CertificateRepository
from app.modules.contact_us.repository import ContactUsRepository
from app.modules.coupon.repository import CouponRepository
from app.modules.course.repository import CourseRepository
from app.modules.course.review_repository import CourseReviewRepository
from app.modules.payment.repository import PaymentRepository
from app.modules.support.entity import SupportTicketStatusEnum
from app.modules.support.repository import SupportTicketRepository
from app.modules.user.entity import UserTypeEnum
from app.modules.user.repository import UserRepository


class AdminDashboardService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_overview(self, limit: int = 5) -> AdminDashboardOverviewDTO:
        now = datetime.now(timezone.utc)
        last_7_days = now - timedelta(days=7)
        last_30_days = now - timedelta(days=30)

        users_repo = UserRepository(self.db)
        by_type = await users_repo.count_by_type()
        users = AdminUserStatsDTO(
            total_users=sum(by_type.values()),
            students=by_type.get(UserTypeEnum.USER, 0),
            instructors=by_type.get(UserTypeEnum.INSTRUCTOR, 0),
            admins=by_type.get(UserTypeEnum.ADMIN, 0),
            suspended=await users_repo.count_suspended(),
            new_last_7_days=await users_repo.count_new_since(last_7_days),
            new_last_30_days=await users_repo.count_new_since(last_30_days),
        )
        recent_signups = [
            RecentSignupDTO(
                id=u.id, first_name=u.first_name, last_name=u.last_name, email=u.email,
                user_type=u.user_type, created_at=u.created_at,
            )
            for u in await users_repo.list_recent(limit)
        ]

        payment_repo = PaymentRepository(self.db)
        revenue = AdminRevenueStatsDTO(
            total_all_time=await payment_repo.sum_revenue(),
            last_30_days=await payment_repo.sum_revenue(since=last_30_days),
            last_7_days=await payment_repo.sum_revenue(since=last_7_days),
            active_subscriptions=await payment_repo.count_active_subscriptions(),
        )
        tx_rows, _ = await payment_repo.list_transactions(PaginationParams(page=1, page_size=limit))
        recent_transactions = [
            RecentTransactionDTO(
                id=tx.id, reference=tx.reference, amount=float(tx.amount), status=tx.status,
                transaction_type=tx.transaction_type, user_id=tx.user_id,
                user_name=f"{user.first_name} {user.last_name}", created_at=tx.created_at,
            )
            for tx, user in tx_rows
        ]

        course_repo = CourseRepository(self.db)
        published, draft = await course_repo.count_by_published_status()
        courses = AdminCourseStatsDTO(total=published + draft, published=published, draft=draft)
        top_enrolled_courses = [
            TopEnrolledCourseDTO(
                course_id=course.id, title=course.title, slug=course.slug,
                thumbnail_url=course.thumbnail_url, enrollment_count=enrollment_count,
            )
            for course, enrollment_count in await course_repo.list_top_enrolled(limit)
        ]

        ticket_repo = SupportTicketRepository(self.db)
        by_status = await ticket_repo.count_by_status()
        support = AdminSupportStatsDTO(
            open=by_status.get(SupportTicketStatusEnum.OPEN, 0),
            in_progress=by_status.get(SupportTicketStatusEnum.IN_PROGRESS, 0),
            resolved=by_status.get(SupportTicketStatusEnum.RESOLVED, 0),
            closed=by_status.get(SupportTicketStatusEnum.CLOSED, 0),
            unassigned_open=await ticket_repo.count_unassigned_open(),
        )

        avg_rating, total_reviews, pending_reply = await CourseReviewRepository(self.db).platform_stats()
        reviews = AdminReviewStatsDTO(
            platform_average_rating=round(avg_rating, 2), total_reviews=total_reviews, pending_reply=pending_reply
        )

        contact_repo = ContactUsRepository(self.db)
        contact_messages = AdminContactStatsDTO(
            total=await contact_repo.count_total(), recent_7_days=await contact_repo.count_since(last_7_days)
        )

        active_coupons = await CouponRepository(self.db).count_active()

        cert_repo = CertificateRepository(self.db)
        certificates_issued_total = await cert_repo.count_total()
        certificates_issued_last_30_days = await cert_repo.count_since(last_30_days)

        return AdminDashboardOverviewDTO(
            users=users,
            revenue=revenue,
            courses=courses,
            top_enrolled_courses=top_enrolled_courses,
            support=support,
            reviews=reviews,
            contact_messages=contact_messages,
            active_coupons=active_coupons,
            certificates_issued_total=certificates_issued_total,
            certificates_issued_last_30_days=certificates_issued_last_30_days,
            recent_signups=recent_signups,
            recent_transactions=recent_transactions,
        )
