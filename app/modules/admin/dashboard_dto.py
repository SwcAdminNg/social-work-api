import uuid
from datetime import datetime

from pydantic import BaseModel

from app.modules.payment.entity import TransactionStatusEnum, TransactionTypeEnum
from app.modules.user.entity import UserTypeEnum


class AdminUserStatsDTO(BaseModel):
    total_users: int
    students: int
    instructors: int
    admins: int
    suspended: int
    new_last_7_days: int
    new_last_30_days: int


class AdminRevenueStatsDTO(BaseModel):
    """`total_all_time`/`last_30_days`/`last_7_days` are all SUCCESS-only
    transaction amounts (what was actually collected, not attempted)."""

    total_all_time: float
    last_30_days: float
    last_7_days: float
    active_subscriptions: int


class AdminCourseStatsDTO(BaseModel):
    total: int
    published: int
    draft: int


class TopEnrolledCourseDTO(BaseModel):
    course_id: uuid.UUID
    title: str
    slug: str
    thumbnail_url: str | None = None
    enrollment_count: int


class AdminSupportStatsDTO(BaseModel):
    open: int
    in_progress: int
    resolved: int
    closed: int
    unassigned_open: int


class AdminReviewStatsDTO(BaseModel):
    platform_average_rating: float
    total_reviews: int
    pending_reply: int


class AdminContactStatsDTO(BaseModel):
    total: int
    recent_7_days: int


class RecentSignupDTO(BaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    user_type: UserTypeEnum
    created_at: datetime


class RecentTransactionDTO(BaseModel):
    id: uuid.UUID
    reference: str
    amount: float
    status: TransactionStatusEnum
    transaction_type: TransactionTypeEnum
    user_id: uuid.UUID
    user_name: str
    created_at: datetime


class AdminDashboardOverviewDTO(BaseModel):
    """Everything the admin dashboard homepage needs in one call. Each stat block
    is also independently derivable from the module's own admin endpoints (see
    the dashboard API doc) for a "view all" drill-down."""

    users: AdminUserStatsDTO
    revenue: AdminRevenueStatsDTO
    courses: AdminCourseStatsDTO
    top_enrolled_courses: list[TopEnrolledCourseDTO]
    support: AdminSupportStatsDTO
    reviews: AdminReviewStatsDTO
    contact_messages: AdminContactStatsDTO
    active_coupons: int
    certificates_issued_total: int
    certificates_issued_last_30_days: int
    recent_signups: list[RecentSignupDTO]
    recent_transactions: list[RecentTransactionDTO]
