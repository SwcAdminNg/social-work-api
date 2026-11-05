"""Public resource library additions used by the website: access filter, category
counts and course names on course-tied resources. No database needed."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import get_db
from app.main import app
from app.modules.resource.dto import ResourceFilterParams, ResourceReadDTO
from app.modules.resource.entity import Resource, ResourceCategoryEnum, ResourceVisibilityEnum
from app.modules.resource.repository import ResourceRepository
from app.modules.resource.service import ResourceService


def _filters(**kwargs) -> ResourceFilterParams:
    base = dict(category=None, course_id=None, search=None, visibility=None)
    return ResourceFilterParams(**{**base, **kwargs})


def _sql(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def test_access_filter_limits_by_visibility():
    repo = ResourceRepository(session=None)
    stmt = repo._apply_filters(select(Resource), _filters(visibility=ResourceVisibilityEnum.LOGGED_IN))
    assert "resources.visibility = 'LOGGED_IN'" in _sql(stmt)


def test_no_access_filter_leaves_query_unchanged():
    repo = ResourceRepository(session=None)
    assert "WHERE" not in _sql(repo._apply_filters(select(Resource), _filters()))


def _dto(course_id=None) -> ResourceReadDTO:
    return ResourceReadDTO(
        id=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
        name="Reflective Practice Worksheet",
        slug="reflective-practice-worksheet",
        category=ResourceCategoryEnum.PRACTICE_RESOURCES,
        description=None,
        thumbnail_url=None,
        visibility=ResourceVisibilityEnum.COURSE_ENROLLED if course_id else ResourceVisibilityEnum.PUBLIC,
        course_id=course_id,
        owner_id=uuid.uuid4(),
        is_published=True,
    )


async def test_course_info_is_attached_in_one_query():
    course_id = uuid.uuid4()
    calls = []

    class FakeSession:
        async def execute(self, stmt):
            calls.append(stmt)
            return SimpleNamespace(all=lambda: [(course_id, "Introduction to Social Work Practice", "intro-practice")])

    tied, standalone = _dto(course_id), _dto()
    await ResourceService(FakeSession()).attach_course_info([tied, standalone])
    assert len(calls) == 1
    assert tied.course_title == "Introduction to Social Work Practice"
    assert tied.course_slug == "intro-practice"
    assert standalone.course_title is None


async def test_course_info_skips_query_when_no_course_ties():
    class NoQuery:
        async def execute(self, stmt):  # pragma: no cover - must not be called
            raise AssertionError("no query expected")

    await ResourceService(NoQuery()).attach_course_info([_dto()])


def test_category_counts_endpoint(monkeypatch):
    async def fake_counts(self):
        return [(ResourceCategoryEnum.POLICIES_AND_GUIDANCE, 3), (ResourceCategoryEnum.VIDEOS_AND_WEBINARS, 1)]

    async def fake_db():
        yield None

    monkeypatch.setattr(ResourceService, "count_published_by_category", fake_counts)
    app.dependency_overrides[get_db] = fake_db
    try:
        with TestClient(app) as client:
            res = client.get("/resources/category-counts")
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert res.status_code == 200, res.text
    assert res.json()["data"] == [
        {"category": "POLICIES_AND_GUIDANCE", "count": 3},
        {"category": "VIDEOS_AND_WEBINARS", "count": 1},
    ]
