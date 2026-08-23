import enum
import uuid

from sqlalchemy import Enum, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity


class ActivityTypeEnum(str, enum.Enum):
    COURSE_ENROLLED = "COURSE_ENROLLED"
    QUIZ_COMPLETED = "QUIZ_COMPLETED"
    QUIZ_GROUP_COMPLETED = "QUIZ_GROUP_COMPLETED"
    ESSAY_SUBMITTED = "ESSAY_SUBMITTED"
    ESSAY_GRADED = "ESSAY_GRADED"
    REVIEW_CREATED = "REVIEW_CREATED"
    REVIEW_EDITED = "REVIEW_EDITED"
    REVIEW_DELETED = "REVIEW_DELETED"
    PAYMENT_SUCCESSFUL = "PAYMENT_SUCCESSFUL"


class ActivityLog(BaseEntity):
    __tablename__ = "activity_logs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    activity_type: Mapped[ActivityTypeEnum] = mapped_column(
        Enum(ActivityTypeEnum, name="activity_type_enum", native_enum=True), nullable=False
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
