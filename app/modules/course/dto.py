import uuid

from fastapi import Query
from pydantic import Field

from app.common.base_dto import AuditDTO, CreateDTO, UpdateDTO
from app.modules.course.entity import CourseCategoryEnum, CourseLevelEnum


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


class CourseFilterParams:
    """Public listing filters - always scoped to published courses by the service."""

    def __init__(
        self,
        category: CourseCategoryEnum | None = Query(None, description="Filter by category"),
        level: CourseLevelEnum | None = Query(None, description="Filter by level"),
        is_free: bool | None = Query(None, description="Filter by free/paid"),
        search: str | None = Query(None, description="Search by title or description"),
    ) -> None:
        self.category = category
        self.level = level
        self.is_free = is_free
        self.search = search


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
