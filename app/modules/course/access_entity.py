import enum
import uuid

from sqlalchemy import Enum, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity


class CourseAccessGrantedViaEnum(str, enum.Enum):
    PURCHASE = "PURCHASE"
    SUBSCRIPTION = "SUBSCRIPTION"
    ADMIN_GRANT = "ADMIN_GRANT"
    FREE = "FREE"


class UserCourseAccess(BaseEntity):
    __tablename__ = "user_course_access"
    __table_args__ = (UniqueConstraint("user_id", "course_id", name="uq_user_course_access"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False, index=True
    )
    granted_via: Mapped[CourseAccessGrantedViaEnum] = mapped_column(
        Enum(CourseAccessGrantedViaEnum, name="course_access_granted_via_enum", native_enum=True),
        nullable=False,
    )
