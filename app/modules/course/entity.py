import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity


class CourseLevelEnum(str, enum.Enum):
    BEGINNER = "BEGINNER"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"


class CourseCategoryEnum(str, enum.Enum):
    DEVELOPMENT = "DEVELOPMENT"
    BUSINESS = "BUSINESS"
    FINANCE_ACCOUNTING = "FINANCE_ACCOUNTING"
    IT_SOFTWARE = "IT_SOFTWARE"
    OFFICE_PRODUCTIVITY = "OFFICE_PRODUCTIVITY"
    PERSONAL_DEVELOPMENT = "PERSONAL_DEVELOPMENT"
    DESIGN = "DESIGN"
    MARKETING = "MARKETING"
    HEALTH_FITNESS = "HEALTH_FITNESS"
    MUSIC = "MUSIC"
    TEACHING_ACADEMICS = "TEACHING_ACADEMICS"
    PHOTOGRAPHY_VIDEO = "PHOTOGRAPHY_VIDEO"
    LIFESTYLE = "LIFESTYLE"
    LANGUAGE = "LANGUAGE"


class CourseItemTypeEnum(str, enum.Enum):
    QUIZ = "QUIZ"
    DOCUMENT = "DOCUMENT"
    VIDEO = "VIDEO"


class Course(BaseEntity):
    __tablename__ = "courses"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(280), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    prerequisite: Mapped[str | None] = mapped_column(Text, nullable=True)
    level: Mapped[CourseLevelEnum] = mapped_column(
        Enum(CourseLevelEnum, name="course_level_enum", native_enum=True), nullable=False
    )
    what_you_will_learn: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    category: Mapped[CourseCategoryEnum] = mapped_column(
        Enum(CourseCategoryEnum, name="course_category_enum", native_enum=True), nullable=False
    )
    material_includes: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    requirements: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    is_free: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    instructor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_exclusive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    featured_order: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CourseCatalog(BaseEntity):
    __tablename__ = "course_catalogs"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(280), unique=True, nullable=False, index=True)
    categories: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    icon_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class CourseSection(BaseEntity):
    __tablename__ = "course_sections"

    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CourseItem(BaseEntity):
    __tablename__ = "course_items"

    section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_sections.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    item_type: Mapped[CourseItemTypeEnum] = mapped_column(
        Enum(CourseItemTypeEnum, name="course_item_type_enum", native_enum=True), nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_preview: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    passing_score: Mapped[int | None] = mapped_column(Integer, nullable=True, default=70)
