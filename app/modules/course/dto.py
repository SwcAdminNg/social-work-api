import enum
import uuid
from datetime import datetime

from fastapi import Query
from pydantic import Field, model_validator

from app.common.base_dto import AuditDTO, BaseDTO, CreateDTO, UpdateDTO
from app.modules.course.entity import CourseAccessModeEnum, CourseCategoryEnum, CourseLevelEnum
from pydantic import BaseModel


class CourseProgressStatusEnum(str, enum.Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class CourseInstructorInputDTO(CreateDTO):
    user_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=255)


class CourseInstructorReadDTO(BaseDTO):
    user_id: uuid.UUID | None = None
    name: str
    profile_picture_url: str | None = None


class _TimedAccessValidatorMixin:
    @model_validator(mode="after")
    def _validate_access_window(self):
        access_mode = getattr(self, "access_mode", None)
        start = getattr(self, "access_start_date", None)
        end = getattr(self, "access_end_date", None)

        if access_mode == CourseAccessModeEnum.SCHEDULED:
            if start is None or end is None:
                raise ValueError(
                    "access_start_date and access_end_date are required when access_mode is SCHEDULED"
                )
            if end <= start:
                raise ValueError("access_end_date must be after access_start_date")
        return self


class CourseCreateDTO(CreateDTO, _TimedAccessValidatorMixin):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    prerequisite: str | None = None
    level: CourseLevelEnum
    what_you_will_learn: list[str] = Field(default_factory=list)
    category: CourseCategoryEnum
    material_includes: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    is_free: bool = True
    price: float | None = Field(default=None, ge=0)
    thumbnail_url: str | None = Field(default=None, max_length=1000)
    is_exclusive: bool = False
    instructors: list[CourseInstructorInputDTO] | None = Field(
        default=None,
        description="Instructors credited on this course. Defaults to the creating "
        "admin/instructor when omitted.",
    )
    access_mode: CourseAccessModeEnum = CourseAccessModeEnum.SELF_PACED
    access_start_date: datetime | None = None
    access_end_date: datetime | None = None


class CourseUpdateDTO(UpdateDTO, _TimedAccessValidatorMixin):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1)
    prerequisite: str | None = None
    level: CourseLevelEnum | None = None
    what_you_will_learn: list[str] | None = None
    category: CourseCategoryEnum | None = None
    material_includes: list[str] | None = None
    requirements: list[str] | None = None
    is_free: bool | None = None
    price: float | None = Field(default=None, ge=0)
    thumbnail_url: str | None = Field(default=None, max_length=1000)
    is_exclusive: bool | None = None
    instructors: list[CourseInstructorInputDTO] | None = None
    access_mode: CourseAccessModeEnum | None = None
    access_start_date: datetime | None = None
    access_end_date: datetime | None = None

    @model_validator(mode="after")
    def _validate_access_window(self):
        # Only enforce when the caller is actually touching access fields - a PATCH
        # payload that doesn't mention any of them shouldn't be forced to re-validate
        # against a SELF_PACED default it never asked for.
        touched = any(
            f in self.model_fields_set for f in ("access_mode", "access_start_date", "access_end_date")
        )
        if not touched:
            return self
        if self.access_mode == CourseAccessModeEnum.SCHEDULED:
            if self.access_start_date is None or self.access_end_date is None:
                raise ValueError(
                    "access_start_date and access_end_date are required when access_mode is SCHEDULED"
                )
            if self.access_end_date <= self.access_start_date:
                raise ValueError("access_end_date must be after access_start_date")
        return self


class CourseReadDTO(AuditDTO):
    title: str
    slug: str
    description: str
    prerequisite: str | None
    level: CourseLevelEnum
    what_you_will_learn: list[str]
    category: CourseCategoryEnum
    material_includes: list[str]
    requirements: list[str]
    is_free: bool
    price: float | None
    thumbnail_url: str | None
    instructor_id: uuid.UUID
    is_published: bool
    is_exclusive: bool
    is_featured: bool
    featured_order: int | None
    average_rating: float
    total_reviews: int
    access_mode: CourseAccessModeEnum
    access_start_date: datetime | None = None
    access_end_date: datetime | None = None
    instructors: list[CourseInstructorReadDTO] = Field(default_factory=list)
    is_bookmarked: bool = False
    is_enrolled: bool = False
    progress_status: CourseProgressStatusEnum | None = Field(
        default=None,
        description="The current user's progress on this course. Only set when the "
        "user is authenticated and enrolled; null otherwise.",
    )

class SetFeaturedCoursesDTO(BaseModel):
    course_ids: list[uuid.UUID]


class CourseCatalogCreateDTO(CreateDTO):
    name: str = Field(min_length=1, max_length=255)
    categories: list[CourseCategoryEnum] = Field(default_factory=list)
    icon_name: str | None = Field(default=None, max_length=255)
    description: str | None = None


class CourseCatalogUpdateDTO(UpdateDTO):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    categories: list[CourseCategoryEnum] | None = None
    icon_name: str | None = Field(default=None, max_length=255)
    description: str | None = None


class CourseCatalogReadDTO(AuditDTO):
    name: str
    slug: str
    categories: list[CourseCategoryEnum]
    icon_name: str | None
    description: str | None


class PublicCourseCatalogReadDTO(CourseCatalogReadDTO):
    total_courses: int = 0


class PublicCourseReadDTO(CourseReadDTO):
    has_access: bool = False



class EnrolledCourseFilterParams:
    """Filters for the current user's enrolled-courses listing."""

    def __init__(
        self,
        search: str | None = Query(
            None, description="Search by course title/description or instructor name"
        ),
        status: CourseProgressStatusEnum | None = Query(
            None, description="Filter by progress status: NOT_STARTED, IN_PROGRESS, or COMPLETED"
        ),
    ) -> None:
        self.search = search
        self.status = status


class CourseFilterParams:
    """Public listing filters - always scoped to published courses by the service."""

    def __init__(
        self,
        category: CourseCategoryEnum | None = Query(None, description="Filter by category"),
        level: CourseLevelEnum | None = Query(None, description="Filter by level"),
        is_free: bool | None = Query(None, description="Filter by free/paid"),
        search: str | None = Query(None, description="Search by title or description"),
        catalog: str | None = Query(None, description="Filter by catalog slug"),
        instructor_id: uuid.UUID | None = Query(
            None, description="Filter by instructor user id (owner or credited instructor)"
        ),
        instructor_name: str | None = Query(
            None, description="Filter by instructor name (partial match, owner or credited instructor)"
        ),
    ) -> None:
        self.category = category
        self.level = level
        self.is_free = is_free
        self.search = search
        self.catalog = catalog
        self.instructor_id = instructor_id
        self.instructor_name = instructor_name


class CourseManageFilterParams(CourseFilterParams):
    """Manage listing filters - instructors only ever see their own courses
    (enforced in the service), admins see everything."""

    def __init__(
        self,
        category: CourseCategoryEnum | None = Query(None, description="Filter by category"),
        level: CourseLevelEnum | None = Query(None, description="Filter by level"),
        is_free: bool | None = Query(None, description="Filter by free/paid"),
        search: str | None = Query(None, description="Search by title or description"),
        is_published: bool | None = Query(None, description="Filter by published state"),
        instructor_id: uuid.UUID | None = Query(
            None, description="Filter by instructor user id (owner or credited instructor)"
        ),
        instructor_name: str | None = Query(
            None, description="Filter by instructor name (partial match, owner or credited instructor)"
        ),
    ) -> None:
        super().__init__(
            category=category,
            level=level,
            is_free=is_free,
            search=search,
            instructor_id=instructor_id,
            instructor_name=instructor_name,
        )
        self.is_published = is_published


class CourseThumbnailUploadRequest(CreateDTO):
    file_name: str
    content_type: str


class CourseThumbnailUploadResponse(CreateDTO):
    upload_url: str
    thumbnail_url: str
