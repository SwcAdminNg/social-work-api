import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cart.dto import CartItemReadDTO, CartReadDTO
from app.modules.cart.entity import CartItem
from app.modules.cart.repository import CartRepository
from app.modules.course.access_entity import UserCourseAccess
from app.modules.course.repository import CourseRepository
from app.modules.user.entity import User


class CartService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = CartRepository(session)
        self.course_repo = CourseRepository(session)

    async def add_item(self, user: User, course_id: uuid.UUID) -> CartReadDTO:
        course = await self.course_repo.get_by_id(course_id)
        if not course or not course.is_published:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
        if course.price is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This course is free - no need to add it to a cart")

        owns_stmt = select(UserCourseAccess.id).where(
            UserCourseAccess.user_id == user.id, UserCourseAccess.course_id == course_id
        )
        if (await self.session.execute(owns_stmt)).scalar_one_or_none() is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "You already have access to this course")

        if await self.repo.get_item(user.id, course_id) is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This course is already in your cart")

        await self.repo.create(CartItem(user_id=user.id, course_id=course_id))
        await self.session.commit()
        return await self.get_cart(user)

    async def get_cart(self, user: User) -> CartReadDTO:
        items = await self.repo.list_for_user(user.id)
        if not items:
            return CartReadDTO(items=[], item_count=0, subtotal_amount=0)

        courses = {c.id: c for c in await self.course_repo.get_many_by_ids([i.course_id for i in items])}
        read_items = []
        for item in items:
            course = courses.get(item.course_id)
            if not course:
                continue
            read_items.append(
                CartItemReadDTO(
                    course_id=course.id,
                    course_title=course.title,
                    course_slug=course.slug,
                    course_thumbnail_url=course.thumbnail_url,
                    price=float(course.price) if course.price is not None else 0.0,
                    added_at=item.created_at,
                )
            )

        subtotal = sum(i.price for i in read_items)
        return CartReadDTO(items=read_items, item_count=len(read_items), subtotal_amount=subtotal)

    async def remove_item(self, user: User, course_id: uuid.UUID) -> CartReadDTO:
        removed = await self.repo.remove_item(user.id, course_id)
        if not removed:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found in cart")
        await self.session.commit()
        return await self.get_cart(user)

    async def clear(self, user: User) -> None:
        await self.repo.clear(user.id)
        await self.session.commit()
