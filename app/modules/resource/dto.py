import uuid

from fastapi import Query
from pydantic import Field, model_validator

from app.common.base_dto import AuditDTO, BaseDTO, CreateDTO, UpdateDTO
from app.modules.resource.entity import ResourceCategoryEnum, ResourceVisibilityEnum


class ResourceCreateDTO(CreateDTO):
    name: str = Field(min_length=1, max_length=255)
    category: ResourceCategoryEnum
    description: str | None = None
    thumbnail_url: str | None = Field(default=None, max_length=1000)
    visibility: ResourceVisibilityEnum = ResourceVisibilityEnum.PUBLIC
    course_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _validate_course_enrolled(self):
        if self.visibility == ResourceVisibilityEnum.COURSE_ENROLLED and self.course_id is None:
            raise ValueError("course_id is required when visibility is COURSE_ENROLLED")
        return self


class ResourceUpdateDTO(UpdateDTO):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    category: ResourceCategoryEnum | None = None
    description: str | None = None
    thumbnail_url: str | None = Field(default=None, max_length=1000)
    visibility: ResourceVisibilityEnum | None = None
    course_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _validate_course_enrolled(self):
        # Only enforce when the caller is actually touching one of these fields in
        # this request - same convention as CourseUpdateDTO's access-window check.
        # The service layer re-checks against the merged/final state too, since a
        # PATCH that only touches one of the two fields can't be judged in isolation.
        touched = any(f in self.model_fields_set for f in ("visibility", "course_id"))
        if not touched:
            return self
        if self.visibility == ResourceVisibilityEnum.COURSE_ENROLLED and self.course_id is None:
            raise ValueError("course_id is required when visibility is COURSE_ENROLLED")
        return self


class ResourceReadDTO(AuditDTO):
    name: str
    slug: str
    category: ResourceCategoryEnum
    description: str | None
    thumbnail_url: str | None
    visibility: ResourceVisibilityEnum
    course_id: uuid.UUID | None
    owner_id: uuid.UUID
    is_published: bool
    can_access: bool = Field(
        default=True,
        description="Whether the current viewer can see this resource's attachments. Always "
        "true for PUBLIC resources; depends on auth/enrollment for LOGGED_IN/COURSE_ENROLLED.",
    )
    access_reason: str | None = Field(
        default=None,
        description="Set only when can_access is false - 'LOGIN_REQUIRED' or 'ENROLLMENT_REQUIRED'.",
    )


class ResourceFilterParams:
    def __init__(
        self,
        category: ResourceCategoryEnum | None = Query(None, description="Filter by category"),
        course_id: uuid.UUID | None = Query(None, description="Filter by tied course"),
        search: str | None = Query(None, description="Search by name or description"),
    ) -> None:
        self.category = category
        self.course_id = course_id
        self.search = search


class ResourceManageFilterParams(ResourceFilterParams):
    def __init__(
        self,
        category: ResourceCategoryEnum | None = Query(None, description="Filter by category"),
        course_id: uuid.UUID | None = Query(None, description="Filter by tied course"),
        search: str | None = Query(None, description="Search by name or description"),
        is_published: bool | None = Query(None, description="Filter by published state"),
    ) -> None:
        super().__init__(category=category, course_id=course_id, search=search)
        self.is_published = is_published


class ResourceThumbnailUploadRequest(CreateDTO):
    file_name: str
    content_type: str


class ResourceThumbnailUploadResponse(CreateDTO):
    upload_url: str
    thumbnail_url: str


class ResourceCardDTO(BaseDTO):
    """Small projection used when a Resource is shared as a card elsewhere (e.g. a
    community chat message referencing a curriculum/material item) - deliberately
    not the full ResourceReadDTO, just enough to render a clickable preview."""

    id: uuid.UUID
    name: str
    slug: str
    category: ResourceCategoryEnum
    thumbnail_url: str | None = None
