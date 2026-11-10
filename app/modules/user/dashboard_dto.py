import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.certificate.dto import CertificateReadDTO
from app.modules.learning.dto import UserLiveSessionDTO
from app.modules.payment.schema import CurrentSubscriptionResponse
from app.modules.user.activity_entity import ActivityTypeEnum


class UserStatsDTO(BaseModel):
    total_courses_enrolled: int
    quizzes_attempted: int
    completion_rate: float
    total_reviews: int
    in_process_courses: int
    completed_courses: int
    not_started_courses: int
    bookmarked_courses: int


class ActivityLogDTO(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    activity_type: ActivityTypeEnum
    metadata_json: dict | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ContinueLearningItemDTO(BaseModel):
    """One in-progress enrolled course - the "Continue learning" rail on the
    dashboard homepage. Deliberately excludes completed courses (those belong in
    the certificates/completed section instead) and is a slim projection of
    `EnrolledCourseDTO`, not the full course payload `GET /learning/courses`
    returns - the dashboard only needs enough to render a card + resume link."""

    course_id: uuid.UUID
    title: str
    slug: str
    thumbnail_url: str | None = None
    progress_percent: int
    last_accessed_at: datetime | None = None
    # Where to resume: lesson counts plus the first item still to do, so the
    # card can say "Lesson 4 of 12" and link straight to it. All optional - a
    # course with no live items yet, or one fully worked through, has no next item.
    total_items: int = 0
    completed_items: int = 0
    next_item_id: uuid.UUID | None = None
    next_item_title: str | None = None
    next_item_type: str | None = None
    next_section_title: str | None = None


class DashboardCountsDTO(BaseModel):
    """The unread and open counts the dashboard header, sidebar and tab bar
    show on every page. Cheap to fetch, so the shell can load it on first
    mount instead of waiting for the homepage overview."""

    unread_notifications_count: int
    unread_community_messages_count: int
    open_support_tickets_count: int
    cart_item_count: int


class DashboardOverviewDTO(BaseModel):
    """Everything the dashboard homepage needs above the fold, composed in one
    request so the frontend isn't firing off 8-10 parallel calls on page load.
    Each section also has its own full/paginated endpoint for a "view all" -
    see the endpoint reference in the dashboard API doc."""

    stats: UserStatsDTO
    continue_learning: list[ContinueLearningItemDTO]
    upcoming_live_sessions: list[UserLiveSessionDTO]
    recent_certificates: list[CertificateReadDTO]
    recent_activity: list[ActivityLogDTO]
    unread_notifications_count: int
    unread_community_messages_count: int
    open_support_tickets_count: int
    cart_item_count: int
    subscription: CurrentSubscriptionResponse | None = None
