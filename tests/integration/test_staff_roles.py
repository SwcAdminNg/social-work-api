"""Staff role listings carry names (not just ids) and can be grouped per person."""

import pytest

from app.core.config import settings
from app.modules.user.entity import UserTypeEnum

pytestmark = pytest.mark.asyncio(loop_scope="session")


def ok(response, status: int | None = None):
    assert response.status_code < 300 if status is None else response.status_code == status, (
        response.status_code, response.text,
    )
    return response.json()


async def test_staff_roles_show_names_and_group_by_person(client, make_user, monkeypatch):
    monkeypatch.setattr(settings, "content_governance_enabled", True)
    admin, admin_h = await make_user("Grantor", UserTypeEnum.ADMIN)
    instructor, instructor_h = await make_user("Author", UserTypeEnum.INSTRUCTOR)
    staff, _ = await make_user("Multirole")

    course_a = ok(await client.post("/courses", json={
        "title": "Alpha Safeguarding", "description": "d", "level": "BEGINNER", "category": "TEACHING_ACADEMICS",
    }, headers=instructor_h), 201)["data"]
    course_b = ok(await client.post("/courses", json={
        "title": "Beta Ethics", "description": "d", "level": "BEGINNER", "category": "TEACHING_ACADEMICS",
    }, headers=instructor_h), 201)["data"]

    granted = ok(await client.post("/admin/staff-roles", json={
        "user_id": str(staff.id), "role": "COURSE_LEAD", "course_id": course_a["id"],
    }, headers=admin_h), 201)["data"]
    assert granted["user"]["name"] == "Multirole Test"
    assert granted["course"] == {"id": course_a["id"], "title": "Alpha Safeguarding"}
    assert granted["granted_by_user"]["name"] == "Grantor Test"

    for body in (
        {"user_id": str(staff.id), "role": "ACADEMIC_REVIEWER", "course_id": course_b["id"]},
        {"user_id": str(staff.id), "role": "QA_REVIEWER"},
    ):
        ok(await client.post("/admin/staff-roles", json=body, headers=admin_h), 201)

    flat = ok(await client.get(f"/admin/staff-roles?user_id={staff.id}", headers=admin_h))["data"]
    assert len(flat) == 3
    assert all(row["user"]["name"] == "Multirole Test" for row in flat)
    platform = next(row for row in flat if row["role"] == "QA_REVIEWER")
    assert "course" not in platform  # platform-wide: no course (nulls are dropped)

    page = ok(await client.get("/admin/staff-roles/members?search=multirole", headers=admin_h))
    assert page["meta"]["total_items"] == 1
    member = page["data"][0]
    assert member["user"]["id"] == str(staff.id)
    assert member["active_role_count"] == 3
    assert member["platform_role_count"] == 1
    assert member["course_count"] == 2
    # Platform-wide first, then courses alphabetically.
    assert [(r["role"], r.get("course", {}).get("title")) for r in member["roles"]] == [
        ("QA_REVIEWER", None),
        ("COURSE_LEAD", "Alpha Safeguarding"),
        ("ACADEMIC_REVIEWER", "Beta Ethics"),
    ]

    scoped = ok(await client.get(f"/admin/staff-roles/members?course_id={course_b['id']}", headers=admin_h))
    assert [m["user"]["id"] for m in scoped["data"]] == [str(staff.id)]
    assert [r["role"] for r in scoped["data"][0]["roles"]] == ["ACADEMIC_REVIEWER"]

    ok(await client.post(f"/admin/staff-roles/{granted['id']}/revoke", json={"reason": "moved"}, headers=admin_h))
    revoked = ok(await client.get("/admin/staff-roles/members?status=REVOKED&search=multirole", headers=admin_h))
    assert [r["role"] for r in revoked["data"][0]["roles"]] == ["COURSE_LEAD"]
    active = ok(await client.get("/admin/staff-roles/members?search=multirole", headers=admin_h))["data"][0]
    assert active["active_role_count"] == 2 and active["course_count"] == 1

    denied = await client.get("/admin/staff-roles/members", headers=instructor_h)
    assert denied.status_code == 403
