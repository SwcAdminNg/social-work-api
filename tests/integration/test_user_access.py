"""`access` on GET /users/me (the same builder feeds the login session)."""

import pytest

from app.core.config import settings
from app.modules.user.entity import UserTypeEnum

pytestmark = pytest.mark.asyncio(loop_scope="session")


def ok(response, status: int | None = None):
    assert response.status_code < 300 if status is None else response.status_code == status, (
        response.status_code, response.text,
    )
    return response.json().get("data")


async def test_profile_access_reflects_roles(client, make_user, monkeypatch):
    monkeypatch.setattr(settings, "content_governance_enabled", True)
    admin, admin_h = await make_user("Boss", UserTypeEnum.ADMIN)
    instructor, instructor_h = await make_user("Teach", UserTypeEnum.INSTRUCTOR)
    learner, learner_h = await make_user("Pupil")

    access = ok(await client.get("/users/me", headers=instructor_h))["access"]
    caps = access["capabilities"]
    assert access["governance_enabled"] is True
    assert caps["can_create_courses"] and caps["can_edit_content"] and caps["can_submit_for_review"]
    assert caps["can_mark_essays"] and not caps["can_publish"] and not caps["can_review_content"]
    assert "SUBMIT_FOR_REVIEW" in access["owned_course_permissions"]

    learner_access = ok(await client.get("/users/me", headers=learner_h))["access"]
    assert not any(learner_access["capabilities"].values())
    assert learner_access["roles"] == []

    course = ok(await client.post("/courses", json={
        "title": "Scoped course", "description": "d", "level": "BEGINNER", "category": "TEACHING_ACADEMICS",
    }, headers=instructor_h), 201)
    ok(await client.post("/admin/staff-roles", json={
        "user_id": str(learner.id), "role": "COURSE_LEAD", "course_id": course["id"],
    }, headers=admin_h), 201)
    learner_access = ok(await client.get("/users/me", headers=learner_h))["access"]
    assert learner_access["capabilities"]["can_review_content"] is True
    assert learner_access["capabilities"]["can_access_approval_centre"] is True
    assert learner_access["course_access"][0]["course_title"] == "Scoped course"
    assert learner_access["course_access"][0]["roles"] == ["COURSE_LEAD"]

    admin_access = ok(await client.get("/users/me", headers=admin_h))["access"]
    assert admin_access["roles"] == ["PLATFORM_ADMIN"]
    assert admin_access["capabilities"]["can_publish"] and not admin_access["capabilities"]["can_review_content"]
