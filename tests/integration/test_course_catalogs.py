"""Course catalog management: create, edit, delete (admin only)."""

import uuid

import pytest

from app.modules.user.entity import UserTypeEnum

pytestmark = pytest.mark.asyncio(loop_scope="session")


def ok(response, status: int | None = None):
    assert response.status_code < 300 if status is None else response.status_code == status, (
        response.status_code, response.text,
    )
    return response.json().get("data")


@pytest.fixture(scope="module")
def s():
    return {}


async def public_catalogs(client):
    return ok(await client.get("/courses/catalogs"))


async def test_01_admin_creates_a_catalog(client, make_user, s):
    admin, admin_h = await make_user("Ada", UserTypeEnum.ADMIN)
    _, learner_h = await make_user("Lerato")
    s.update(admin_h=admin_h, learner_h=learner_h)

    created = ok(await client.post("/courses/catalogs", json={
        "name": "  Practice Skills  ", "categories": ["TEACHING_ACADEMICS", "PERSONAL_DEVELOPMENT"],
        "icon_name": "BookOpen", "description": "Hands-on skills",
    }, headers=admin_h), 201)
    assert created["name"] == "Practice Skills"  # trimmed
    assert created["slug"] == "practice-skills"
    s["id"] = created["id"]

    # Names are unique, ignoring case and surrounding spaces.
    dup = await client.post("/courses/catalogs", json={
        "name": "practice skills", "categories": ["DESIGN"],
    }, headers=admin_h)
    assert dup.status_code == 409, dup.text

    assert s["id"] in {c["id"] for c in await public_catalogs(client)}


async def test_02_only_admins_can_edit_or_delete(client, s):
    body = {"name": "Hijacked"}
    assert (await client.patch(f"/courses/catalogs/{s['id']}", json=body, headers=s["learner_h"])).status_code == 403
    assert (await client.delete(f"/courses/catalogs/{s['id']}", headers=s["learner_h"])).status_code == 403
    assert (await client.patch(f"/courses/catalogs/{s['id']}", json=body)).status_code in (401, 403)


async def test_03_admin_edits_a_catalog(client, s):
    h = s["admin_h"]
    updated = ok(await client.patch(f"/courses/catalogs/{s['id']}", json={
        "name": "Applied Practice", "description": "  ", "icon_name": "Users",
        "categories": ["TEACHING_ACADEMICS", "LANGUAGE", "LANGUAGE"],
    }, headers=h))
    assert updated["name"] == "Applied Practice"
    assert updated["icon_name"] == "Users"
    assert updated.get("description") is None  # blank clears it
    assert updated["categories"] == ["TEACHING_ACADEMICS", "LANGUAGE"]  # de-duplicated, order kept
    assert updated["slug"] == "practice-skills"  # links to the catalog keep working

    # The public list reflects the edit straight away (cache is invalidated).
    listed = next(c for c in await public_catalogs(client) if c["id"] == s["id"])
    assert listed["name"] == "Applied Practice"

    # Partial update leaves other fields alone.
    ok(await client.patch(f"/courses/catalogs/{s['id']}", json={"description": "Back again"}, headers=h))
    listed = next(c for c in await public_catalogs(client) if c["id"] == s["id"])
    assert listed["description"] == "Back again" and listed["icon_name"] == "Users"


async def test_04_edit_validation(client, make_user, s):
    h = s["admin_h"]
    other = ok(await client.post("/courses/catalogs", json={
        "name": "Wellbeing", "categories": ["HEALTH_FITNESS"],
    }, headers=h), 201)
    s["other_id"] = other["id"]

    clash = await client.patch(f"/courses/catalogs/{other['id']}", json={"name": "applied practice"}, headers=h)
    assert clash.status_code == 409, clash.text
    # Renaming a catalog to its own name (different case) is fine.
    ok(await client.patch(f"/courses/catalogs/{other['id']}", json={"name": "WELLBEING"}, headers=h))

    assert (await client.patch(f"/courses/catalogs/{other['id']}", json={"categories": []}, headers=h)).status_code == 400
    assert (await client.patch(f"/courses/catalogs/{other['id']}", json={"name": "   "}, headers=h)).status_code in (400, 422)
    assert (await client.patch(f"/courses/catalogs/{uuid.uuid4()}", json={"name": "Nope"}, headers=h)).status_code == 404


async def test_05_admin_deletes_a_catalog(client, s):
    h = s["admin_h"]
    ok(await client.delete(f"/courses/catalogs/{s['id']}", headers=h))

    ids = {c["id"] for c in await public_catalogs(client)}
    assert s["id"] not in ids and s["other_id"] in ids  # only that catalog goes

    # Gone for good from the API's point of view.
    assert (await client.delete(f"/courses/catalogs/{s['id']}", headers=h)).status_code == 404
    assert (await client.patch(f"/courses/catalogs/{s['id']}", json={"name": "Zombie"}, headers=h)).status_code == 404

    # A deleted catalog's name and slug can be reused.
    again = ok(await client.post("/courses/catalogs", json={
        "name": "Applied Practice", "categories": ["LANGUAGE"],
    }, headers=h), 201)
    assert again["id"] != s["id"] and again["slug"].startswith("applied-practice")
