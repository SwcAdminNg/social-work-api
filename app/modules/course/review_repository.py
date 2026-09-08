import uuid
from typing import Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.pagination import PaginationParams
from app.modules.course.entity import Course
from app.modules.course.review_entity import CourseReview


class CourseReviewRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, review_id: uuid.UUID) -> CourseReview | None:
        stmt = select(CourseReview).where(CourseReview.id == review_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_course_and_user(self, course_id: uuid.UUID, user_id: uuid.UUID) -> CourseReview | None:
        stmt = select(CourseReview).where(
            CourseReview.course_id == course_id, CourseReview.user_id == user_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_course_reviews(
        self, course_id: uuid.UUID, pagination: PaginationParams
    ) -> Tuple[Sequence[CourseReview], int]:
        # Only fetch public/unhidden reviews for listing
        base_stmt = select(CourseReview).where(
            CourseReview.course_id == course_id,
            CourseReview.is_hidden.is_(False)
        )
        
        # Count
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Paginated fetch with user loaded
        # We need to eager load the user to include their name in the response
        # Using a join or selectinload, assuming there is a relationship set up. 
        # But wait, we didn't add a relationship on CourseReview to User. We might need to join manually or add the relationship.
        # Let's join manually since relationship wasn't explicitly defined in review_entity.py
        from app.modules.user.entity import User
        
        stmt = (
            base_stmt
            .join(User, User.id == CourseReview.user_id)
            .add_columns(User)
            .order_by(CourseReview.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
        
        result = await self.session.execute(stmt)
        rows = result.all()
        
        reviews = []
        for review, user in rows:
            review.user = user
            reviews.append(review)
            
        return reviews, total

    async def list_all_reviews_for_admin(
        self, pagination: PaginationParams
    ) -> Tuple[Sequence[CourseReview], int]:
        from app.modules.user.entity import User

        base_stmt = select(CourseReview)
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            base_stmt
            .join(User, User.id == CourseReview.user_id)
            .join(Course, Course.id == CourseReview.course_id)
            .add_columns(User)
            .add_columns(Course)
            .order_by(CourseReview.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
        
        result = await self.session.execute(stmt)
        rows = result.all()
        
        reviews = []
        for review, user, course in rows:
            review.user = user
            review.course = course
            reviews.append(review)
            
        return reviews, total

    async def platform_stats(self) -> tuple[float, int, int]:
        """Returns (average_rating, total_reviews, pending_reply_count) across every
        non-hidden review platform-wide. "Pending reply" = a review with no
        `reply_text` yet, regardless of rating - the admin queue for "reviews that
        need a response"."""
        stats_stmt = select(func.avg(CourseReview.rating), func.count()).where(CourseReview.is_hidden.is_(False))
        avg_rating, total = (await self.session.execute(stats_stmt)).one()

        pending_stmt = select(func.count()).select_from(
            select(CourseReview)
            .where(CourseReview.is_hidden.is_(False), CourseReview.reply_text.is_(None))
            .subquery()
        )
        pending = (await self.session.execute(pending_stmt)).scalar_one()

        return (float(avg_rating) if avg_rating is not None else 0.0, total or 0, pending)

    async def create(self, review: CourseReview) -> CourseReview:
        self.session.add(review)
        await self.session.flush()
        return review

    async def delete(self, review: CourseReview) -> None:
        await self.session.delete(review)
        await self.session.flush()

    async def recalculate_course_rating(self, course_id: uuid.UUID) -> None:
        # Calculate the new average and count
        stmt = select(
            func.avg(CourseReview.rating),
            func.count(CourseReview.rating)
        ).where(
            CourseReview.course_id == course_id,
            CourseReview.is_hidden.is_(False)
        )
        
        result = await self.session.execute(stmt)
        avg_rating, total_reviews = result.one()
        
        avg_rating = float(avg_rating) if avg_rating is not None else 0.0
        total_reviews = total_reviews if total_reviews is not None else 0

        # Update the course
        course_stmt = select(Course).where(Course.id == course_id)
        course_result = await self.session.execute(course_stmt)
        course = course_result.scalar_one_or_none()
        
        if course:
            course.average_rating = avg_rating
            course.total_reviews = total_reviews
            self.session.add(course)
            await self.session.flush()
