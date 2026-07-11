import uuid
from datetime import datetime, timezone
from typing import Sequence, Tuple

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.modules.course.review_dto import ReviewCreate, ReviewHideDTO, ReviewReplyDTO, ReviewUpdate
from app.modules.course.review_entity import CourseReview
from app.modules.course.review_repository import CourseReviewRepository
from app.modules.course.service import CourseService
from app.modules.user.activity_entity import ActivityTypeEnum
from app.modules.user.activity_service import ActivityService
from app.modules.user.entity import User, UserTypeEnum
from app.core.cache import delete_cache, get_cache, set_cache


class CourseReviewService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CourseReviewRepository(db)
        self.course_service = CourseService(db)
        self.activity_service = ActivityService(db)

    async def get_review_by_id(self, review_id: uuid.UUID) -> CourseReview:
        review = await self.repo.get_by_id(review_id)
        if not review:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
        return review

    async def create_review(
        self, course_id: uuid.UUID, payload: ReviewCreate, current_user: User
    ) -> CourseReview:
        # Check if course exists
        course = await self.course_service.get_by_id(course_id)
        
        # Check if user is enrolled
        enrolled_ids, _ = await self.course_service.get_course_access_details(current_user, [course_id])
        if course_id not in enrolled_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="You must be enrolled in this course to leave a review."
            )

        # Check if review already exists
        existing_review = await self.repo.get_by_course_and_user(course_id, current_user.id)
        if existing_review:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail="You have already reviewed this course."
            )

        review = CourseReview(
            course_id=course_id,
            user_id=current_user.id,
            rating=payload.rating,
            review_text=payload.review_text,
        )
        
        created_review = await self.repo.create(review)
        await self.repo.recalculate_course_rating(course_id)
        
        await self.activity_service.log_activity(
            current_user.id,
            ActivityTypeEnum.REVIEW_CREATED,
            {"course_id": str(course_id), "course_title": course.title, "review_id": str(created_review.id), "rating": float(created_review.rating)}
        )
        
        await self.db.commit()
        
        await delete_cache(f"course:slug:{course.slug}")
        await delete_cache("courses:*")
        await delete_cache(f"reviews:course_{course_id}:*")
        
        await self.db.refresh(created_review)
        return created_review

    async def update_review(
        self, review_id: uuid.UUID, payload: ReviewUpdate, current_user: User
    ) -> CourseReview:
        review = await self.get_review_by_id(review_id)
        
        if review.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="You can only update your own reviews."
            )

        if payload.rating is not None:
            review.rating = payload.rating
        if payload.review_text is not None:
            review.review_text = payload.review_text
            
        await self.repo.recalculate_course_rating(review.course_id)
        
        course = await self.course_service.get_by_id(review.course_id)
        await self.activity_service.log_activity(
            current_user.id,
            ActivityTypeEnum.REVIEW_EDITED,
            {"course_id": str(review.course_id), "course_title": course.title, "review_id": str(review.id), "rating": float(review.rating)}
        )
        
        await self.db.commit()
        
        await delete_cache(f"course:slug:{course.slug}")
        await delete_cache("courses:*")
        await delete_cache(f"reviews:course_{review.course_id}:*")
        
        await self.db.refresh(review)
        return review

    async def delete_review(self, review_id: uuid.UUID, current_user: User) -> None:
        review = await self.get_review_by_id(review_id)
        
        # Allow admins or the owner to delete
        if review.user_id != current_user.id and current_user.user_type != UserTypeEnum.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="Not authorized to delete this review."
            )

        course_id = review.course_id
        await self.repo.delete(review)
        await self.repo.recalculate_course_rating(course_id)
        
        course = await self.course_service.get_by_id(course_id)
        await self.activity_service.log_activity(
            current_user.id,
            ActivityTypeEnum.REVIEW_DELETED,
            {"course_id": str(course_id), "course_title": course.title, "review_id": str(review_id)}
        )
        
        await self.db.commit()
        
        await delete_cache(f"course:slug:{course.slug}")
        await delete_cache("courses:*")
        await delete_cache(f"reviews:course_{course_id}:*")

    async def list_course_reviews(
        self, course_id: uuid.UUID, pagination: PaginationParams
    ) -> Tuple[Sequence[CourseReview], int]:
        return await self.repo.list_course_reviews(course_id, pagination)

    async def list_all_reviews_for_admin(
        self, pagination: PaginationParams, current_user: User
    ) -> Tuple[Sequence[CourseReview], int]:
        if current_user.user_type != UserTypeEnum.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="Only admins can list all reviews."
            )
        return await self.repo.list_all_reviews_for_admin(pagination)
        
        
    async def get_my_review(self, course_id: uuid.UUID, current_user: User) -> CourseReview:
        review = await self.repo.get_by_course_and_user(course_id, current_user.id)
        if not review:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="You haven't reviewed this course yet."
            )
        return review
        
    async def reply_to_review(
        self, review_id: uuid.UUID, payload: ReviewReplyDTO, current_user: User
    ) -> CourseReview:
        review = await self.get_review_by_id(review_id)
        
        # Must be course instructor or admin
        course = await self.course_service.get_by_id(review.course_id)
        if course.instructor_id != current_user.id and current_user.user_type != UserTypeEnum.ADMIN:
             raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="Only the course instructor or an admin can reply to reviews."
            )
            
        review.reply_text = payload.reply_text
        review.reply_created_at = datetime.now(timezone.utc)
        
        await self.db.commit()
        await delete_cache(f"reviews:course_{review.course_id}:*")
        await self.db.refresh(review)
        return review

    async def hide_review(
        self, review_id: uuid.UUID, payload: ReviewHideDTO, current_user: User
    ) -> CourseReview:
        # Admin only
        if current_user.user_type != UserTypeEnum.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="Only admins can hide or unhide reviews."
            )
            
        review = await self.get_review_by_id(review_id)
        review.is_hidden = payload.is_hidden
        
        await self.repo.recalculate_course_rating(review.course_id)
        await self.db.commit()
        
        course = await self.course_service.get_by_id(review.course_id)
        await delete_cache(f"course:slug:{course.slug}")
        await delete_cache("courses:*")
        await delete_cache(f"reviews:course_{review.course_id}:*")
        
        await self.db.refresh(review)
        return review
