import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity


class ResourceCategoryEnum(str, enum.Enum):
    COURSE_MATERIALS = "COURSE_MATERIALS"
    PRACTICE_RESOURCES = "PRACTICE_RESOURCES"
    POLICIES_AND_GUIDANCE = "POLICIES_AND_GUIDANCE"
    TEMPLATES_AND_FORMS = "TEMPLATES_AND_FORMS"
    VIDEOS_AND_WEBINARS = "VIDEOS_AND_WEBINARS"
    RESEARCH_AND_PUBLICATIONS = "RESEARCH_AND_PUBLICATIONS"
    CAREER_AND_CPD = "CAREER_AND_CPD"
    USEFUL_LINKS = "USEFUL_LINKS"


class ResourceVisibilityEnum(str, enum.Enum):
    PUBLIC = "PUBLIC"
    LOGGED_IN = "LOGGED_IN"
    COURSE_ENROLLED = "COURSE_ENROLLED"


class ResourceAttachmentTypeEnum(str, enum.Enum):
    VIDEO = "VIDEO"
    DOCUMENT = "DOCUMENT"
    LINKS = "LINKS"


class Resource(BaseEntity):
    """A standalone library item (policy, template, guide, webinar recording,
    useful link, etc.) shown in the general resource library and/or a specific
    course's page. Unlike `CourseItem`, a Resource may carry multiple
    attachments (see `ResourceAttachment`) and isn't part of any curriculum
    ordering/progress-tracking flow - it's reference material, not a lesson."""

    __tablename__ = "resources"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(280), unique=True, nullable=False, index=True)
    category: Mapped[ResourceCategoryEnum] = mapped_column(
        Enum(ResourceCategoryEnum, name="resource_category_enum", native_enum=True), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    visibility: Mapped[ResourceVisibilityEnum] = mapped_column(
        Enum(ResourceVisibilityEnum, name="resource_visibility_enum", native_enum=True),
        nullable=False,
        default=ResourceVisibilityEnum.PUBLIC,
        server_default=ResourceVisibilityEnum.PUBLIC.value,
    )
    # Nullable - a resource can stand entirely on its own. Required (validated at
    # the DTO layer) when visibility == COURSE_ENROLLED, since that's the only
    # tier that means anything relative to a course.
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id"), nullable=True, index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
