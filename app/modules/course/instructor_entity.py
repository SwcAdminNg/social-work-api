import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity


class CourseInstructor(BaseEntity):
    """A named instructor credited on a course. `user_id` is optional so admins/
    instructors can credit a guest instructor who has no platform account; when
    it is set it is usable for filtering courses by instructor."""

    __tablename__ = "course_instructors"

    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Explicit flag for a guest lecturer credited on the course (typically via a
    # CourseSectionInstructor link for a specific section) rather than a regular
    # instructor. Distinct from `user_id is None`, which only means "no platform
    # account" and can also apply to a regular instructor who hasn't signed up yet.
    is_guest: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")


class CourseSectionInstructor(BaseEntity):
    """Links a CourseInstructor (most commonly a guest lecturer) to the specific
    CourseSection they're credited for, when a section is taught by someone other
    than the course's regular instructor(s). The linked CourseInstructor row is
    what actually credits them on the course - this table just says which
    section(s) they cover."""

    __tablename__ = "course_section_instructors"

    section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_sections.id"), nullable=False, index=True
    )
    course_instructor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_instructors.id"), nullable=False, index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
