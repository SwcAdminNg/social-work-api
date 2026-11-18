"""Free previews on the public course page, and JAD AI on interactive (SCORM) lessons.

Reuses the in-memory R2 stand-in from the SCORM suite so packages run through the
real upload -> finalize -> launch path.
"""

import io
import zipfile

import pytest

from app.core.config import settings
from app.core.storage import get_r2_client
from app.modules.jad_ai import llm
from app.modules.user.entity import UserTypeEnum
from tests.integration.test_scorm_flow import FakeS3, make_package_zip

pytestmark = pytest.mark.asyncio(loop_scope="session")


def ok(response, status: int | None = None):
    assert response.status_code < 300 if status is None else response.status_code == status, (
        response.status_code, response.text,
    )
    return response.json().get("data")


@pytest.fixture(autouse=True)
def settings_for_suite(monkeypatch):
    monkeypatch.setattr(settings, "content_governance_enabled", False)
    monkeypatch.setattr(settings, "jad_ai_enabled", True)
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_api_key", "")

    async def json_chat(system, user, max_tokens=400):
        return {"suggestions": ["What is SAFER?", "Explain Scan", "Give me an example"]}

    monkeypatch.setattr(llm, "json_chat", json_chat)


@pytest.fixture(scope="module")
def fake_s3():
    r2 = get_r2_client()
    original = r2._client
    fake = FakeS3()
    r2._client = fake
    yield fake
    r2._client = original


@pytest.fixture(scope="module")
def state():
    return {}


async def _scorm_item(client, fake_s3, cid, sid, headers, title, *, preview=False, order=0):
    created = ok(await client.post(f"/courses/{cid}/sections/{sid}/items", json={
        "title": title, "item_type": "SCORM", "file_name": f"pkg-{order}.zip",
        "is_preview": preview, "order_index": order,
    }, headers=headers), 201)
    fake_s3.put_object(Bucket="x", Key=created["scorm_upload"]["storage_key"], Body=make_package_zip(),
                       ContentType="application/zip")
    ok(await client.post(f"/courses/items/{created['id']}/scorm/finalize", json={}, headers=headers))
    return created["id"]


async def _doc_item(client, fake_s3, cid, sid, headers, title, *, preview, downloadable, order):
    created = ok(await client.post(f"/courses/{cid}/sections/{sid}/items", json={
        "title": title, "item_type": "DOCUMENT", "file_name": "lesson.pdf",
        "is_preview": preview, "downloadable": downloadable, "order_index": order,
    }, headers=headers), 201)
    fake_s3.put_object(Bucket="x", Key=created["document_upload"]["storage_key"], Body=b"%PDF-1.4",
                       ContentType="application/pdf")
    ok(await client.post(f"/courses/items/{created['id']}/document/finalize",
                         json={"mime_type": "application/pdf"}, headers=headers))
    return created["id"]


async def test_setup_course_with_preview_items(client, make_user, state, fake_s3):
    admin, admin_h = await make_user("Ada", UserTypeEnum.ADMIN)
    course = ok(await client.post("/courses", json={
        "title": "Preview Course", "description": "Free previews", "level": "BEGINNER",
        "category": "TEACHING_ACADEMICS", "what_you_will_learn": ["Previews"],
    }, headers=admin_h), 201)
    cid, slug = course["id"], course["slug"]
    sid = ok(await client.post(f"/courses/{cid}/sections", json={"title": "Module 1"}, headers=admin_h), 201)["id"]

    state.update(
        admin_h=admin_h, cid=cid, slug=slug,
        scorm_preview=await _scorm_item(client, fake_s3, cid, sid, admin_h, "Interactive: Welcome", preview=True, order=0),
        scorm_locked=await _scorm_item(client, fake_s3, cid, sid, admin_h, "Interactive: SAFER pathway", order=1),
        scorm_assessment=await _scorm_item(client, fake_s3, cid, sid, admin_h, "Module 1 Assessment (Interactive)", order=2),
        doc_preview=await _doc_item(client, fake_s3, cid, sid, admin_h, "Lesson 1.1", preview=True, downloadable=False, order=3),
        doc_download=await _doc_item(client, fake_s3, cid, sid, admin_h, "Lesson 1.2", preview=True, downloadable=True, order=4),
    )

    # Nothing is previewable while the course is unpublished.
    ok(await client.get(f"/courses/{slug}/items/{state['scorm_preview']}/preview"), 404)
    ok(await client.patch(f"/courses/{cid}/publish?is_published=true", headers=admin_h))


async def test_visitor_previews_scorm_without_saving(client, state):
    data = ok(await client.get(f"/courses/{state['slug']}/items/{state['scorm_preview']}/preview"))
    assert data["item_type"] == "SCORM"
    assert "/scorm/" in data["launch_url"] and data["launch_url"].endswith("/index.html")
    assert not data.get("view_url")

    token = data["launch_url"].split("/scorm/")[1].split("/")[0]
    page = await client.get(f"/scorm/{token}/index.html")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert '"mode": "preview"' in page.text and "window.API = {" in page.text
    assert '"commitUrl": null' in page.text
    asset = await client.get(f"/scorm/{token}/assets/audio/1-01.mp3")
    assert asset.status_code == 200

    saved = ok(await client.post(f"/scorm/{token}/_lms/commit",
                                 json={"session_id": "s1", "data": {"cmi.core.lesson_status": "completed"}}))
    assert saved["is_completed"] is False


async def test_only_free_preview_items_open(client, state):
    ok(await client.get(f"/courses/{state['slug']}/items/{state['scorm_locked']}/preview"), 403)
    ok(await client.get(f"/courses/no-such-course/items/{state['scorm_preview']}/preview"), 404)


async def test_visitor_previews_documents(client, state):
    viewable = ok(await client.get(f"/courses/{state['slug']}/items/{state['doc_preview']}/preview"))
    assert viewable["item_type"] == "DOCUMENT" and viewable["view_url"].startswith("https://fake-r2.test/")
    assert viewable.get("download_url") is None  # not marked downloadable
    assert viewable["file_name"] == "lesson.pdf"

    downloadable = ok(await client.get(f"/courses/{state['slug']}/items/{state['doc_download']}/preview"))
    assert downloadable["download_url"].startswith("https://fake-r2.test/")


async def test_jad_reads_scorm_lessons_but_not_scorm_assessments(client, make_user, state, fake_s3):
    learner, learner_h = await make_user("Lerato")
    ok(await client.post(f"/learning/courses/{state['cid']}/enroll", headers=learner_h))

    lesson = ok(await client.get(f"/jad-ai/courses/{state['cid']}/items/{state['scorm_locked']}", headers=learner_h))
    assert lesson["available"] is True and lesson["lesson_kind"] == "scorm"

    ok(await client.get(f"/jad-ai/courses/{state['cid']}/items/{state['scorm_assessment']}", headers=learner_h), 403)


def test_package_zip_helper_still_builds():
    # Guards the shared helper this suite imports.
    with zipfile.ZipFile(io.BytesIO(make_package_zip())) as zf:
        assert any(n.endswith("index.html") for n in zf.namelist())
