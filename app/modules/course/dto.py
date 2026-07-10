import uuid

from fastapi import Query
from pydantic import Field

from app.common.base_dto import AuditDTO, CreateDTO, UpdateDTO
from app.modules.course.entity import CourseCategoryEnum, CourseLevelEnum
from pydantic import BaseModel


class CourseCreateDTO(CreateDTO):
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


class CourseUpdateDTO(UpdateDTO):
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
    is_enrolled: bool = False
    has_access: bool = False



class CourseFilterParams:
    """Public listing filters - always scoped to published courses by the service."""

    def __init__(
        self,
        category: CourseCategoryEnum | None = Query(None, description="Filter by category"),
        level: CourseLevelEnum | None = Query(None, description="Filter by level"),
        is_free: bool | None = Query(None, description="Filter by free/paid"),
        search: str | None = Query(None, description="Search by title or description"),
        catalog: str | None = Query(None, description="Filter by catalog slug"),
    ) -> None:
        self.category = category
        self.level = level
        self.is_free = is_free
        self.search = search
        self.catalog = catalog


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
    ) -> None:
        super().__init__(category=category, level=level, is_free=is_free, search=search)
        self.is_published = is_published


class CourseThumbnailUploadRequest(CreateDTO):
    file_name: str
    content_type: str


class CourseThumbnailUploadResponse(CreateDTO):
    upload_url: str
    thumbnail_url: str
