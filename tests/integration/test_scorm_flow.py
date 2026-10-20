"""End-to-end SCORM / interactive-package flow against the disposable database.

Storage is swapped for an in-memory stand-in for R2 so the test can run the
real upload -> finalize (unpack) -> learner launch -> runtime commit path.
"""

import io
import json
import re
import uuid
import zipfile

import pytest

from app.core.config import settings
from app.core.storage import get_r2_client
from app.modules.user.entity import UserTypeEnum

pytestmark = pytest.mark.asyncio(loop_scope="session")


def ok(response, status: int | None = None):
    assert response.status_code < 300 if status is None else response.status_code == status, (
        response.status_code, response.text,
    )
    return response.json().get("data")


class _NoSuchKey(Exception):
    pass


class _Exceptions:
    NoSuchKey = _NoSuchKey


class FakeS3:
    """Just enough of boto3's S3 client for scorm.py: objects live in a dict."""

    exceptions = _Exceptions()

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[Key] = (Body if isinstance(Body, bytes) else Body.read(), ContentType or "binary/octet-stream")

    def get_object(self, Bucket, Key, Range=None):
        if Key not in self.objects:
            raise _NoSuchKey()
        data, content_type = self.objects[Key]
        out = {"ContentType": content_type}
        if Range:
            start, end = re.match(r"bytes=(\d*)-(\d*)", Range).groups()
            start = int(start or 0)
            end = int(end) if end else len(data) - 1
            chunk = data[start : end + 1]
            out["ContentRange"] = f"bytes {start}-{end}/{len(data)}"
            out["ContentLength"] = len(chunk)
            out["Body"] = _Body(chunk)
        else:
            out["ContentLength"] = len(data)
            out["Body"] = _Body(data)
        return out

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://fake-r2.test/{Params['Key']}?op={op}"

    def delete_object(self, **kw):
        self.objects.pop(kw["Key"], None)


class _Body:
    def __init__(self, data: bytes) -> None:
        self._buf = io.BytesIO(data)

    def read(self):
        return self._buf.read()

    def iter_chunks(self, size):
        while True:
            chunk = self._buf.read(size)
            if not chunk:
                return
            yield chunk


@pytest.fixture(autouse=True)
def governance_off(monkeypatch):
    # Plain publish toggle; the review workflow has its own suites.
    monkeypatch.setattr(settings, "content_governance_enabled", False)


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


def make_package_zip(wrapper: str = "SWC-Module1") -> bytes:
    manifest = """<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="SWC_RCA_M1_CH1" version="1.0" xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
  xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2">
  <metadata><schema>ADL SCORM</schema><schemaversion>1.2</schemaversion></metadata>
  <organizations default="ORG"><organization identifier="ORG"><title>Chapter 1: Objectives</title>
    <item identifier="ITEM" identifierref="RES"><title>Chapter 1</title></item></organization></organizations>
  <resources><resource identifier="RES" type="webcontent" adlcp:scormtype="sco" href="index.html">
    <file href="index.html"/><file href="assets/audio/1-01.mp3"/></resource></resources>
</manifest>"""
    html = "<!doctype html><html><head><title>Ch1</title></head><body><script>window.API.LMSInitialize('')</script></body></html>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{wrapper}/imsmanifest.xml", manifest)
        zf.writestr(f"{wrapper}/index.html", html)
        zf.writestr(f"{wrapper}/assets/audio/1-01.mp3", bytes(range(256)) * 4)
        zf.writestr("__MACOSX/._index.html", "junk")
    return buf.getvalue()


async def test_staff_creates_and_uploads_package(client, make_user, state, fake_s3):
    admin, admin_h = await make_user("Ada", UserTypeEnum.ADMIN)
    learner, learner_h = await make_user("Lerato")
    course = ok(
        await client.post(
            "/courses",
            json={
                "title": "Responding to Child Abuse", "description": "Module 1", "level": "BEGINNER",
                "category": "TEACHING_ACADEMICS", "what_you_will_learn": ["Objectives"],
            },
            headers=admin_h,
        ),
        201,
    )
    cid = course["id"]
    section = ok(await client.post(f"/courses/{cid}/sections", json={"title": "Module 1"}, headers=admin_h), 201)

    # A non-zip name is refused up front.
    bad = await client.post(
        f"/courses/{cid}/sections/{section['id']}/items",
        json={"title": "Ch1", "item_type": "SCORM", "file_name": "package.rar"},
        headers=admin_h,
    )
    assert bad.status_code == 400, bad.text

    created = ok(
        await client.post(
            f"/courses/{cid}/sections/{section['id']}/items",
            json={"title": "Chapter 1: Objectives", "item_type": "SCORM", "file_name": "swc-m1-ch1.zip"},
            headers=admin_h,
        ),
        201,
    )
    assert created["item_type"] == "SCORM"
    assert created["scorm_upload"]["upload_url"].startswith("https://fake-r2.test/")
    storage_key = created["scorm_upload"]["storage_key"]

    # The client PUTs the zip to R2 directly - simulate that, then finalize.
    fake_s3.put_object(Bucket="x", Key=storage_key, Body=make_package_zip(), ContentType="application/zip")
    finalized = ok(
        await client.post(
            f"/courses/items/{created['id']}/scorm/finalize", json={"file_size_bytes": 1234}, headers=admin_h
        )
    )
    pkg = finalized["scorm"]
    assert pkg["status"] == "READY"
    assert pkg["launch_path"] == "index.html"
    assert pkg["scorm_version"] == "1.2"
    assert pkg["manifest_title"] == "Chapter 1: Objectives"
    assert pkg["file_count"] == 3
    extracted_keys = [k for k in fake_s3.objects if "/scorm/packages/" in k]
    assert any(k.endswith("/index.html") for k in extracted_keys)
    assert any(k.endswith("/assets/audio/1-01.mp3") for k in extracted_keys)
    assert not any("__MACOSX" in k or "SWC-Module1/" in k for k in extracted_keys)

    manage = ok(await client.get(f"/courses/manage/{cid}", headers=admin_h))
    item = manage["sections"][0]["items"][0]
    assert item["scorm"]["status"] == "READY" and item["scorm"]["file_name"] == "swc-m1-ch1.zip"

    # Staff preview launches in browse mode and never saves.
    preview = ok(await client.get(f"/courses/items/{created['id']}/scorm/preview", headers=admin_h))
    assert "/scorm/" in preview["launch_url"] and preview["launch_url"].endswith("/index.html")
    token = preview["launch_url"].split("/scorm/")[1].split("/")[0]
    page = await client.get(f"/scorm/{token}/index.html")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert '"mode": "preview"' in page.text and "window.API = {" in page.text
    saved = ok(await client.post(f"/scorm/{token}/_lms/commit", json={"session_id": "s1", "data": {"cmi.core.lesson_status": "completed"}}))
    assert saved["is_completed"] is False

    ok(await client.patch(f"/courses/{cid}/publish?is_published=true", headers=admin_h))
    state.update(admin_h=admin_h, learner_h=learner_h, course_id=cid, item_id=created["id"], learner=learner)


async def test_learner_plays_package_and_progress_is_saved(client, state, fake_s3):
    cid, item_id, lh = state["course_id"], state["item_id"], state["learner_h"]
    ok(await client.post(f"/learning/courses/{cid}/enroll", headers=lh))

    content = ok(await client.get(f"/learning/courses/{cid}/items/{item_id}", headers=lh))
    assert content["item_type"] == "SCORM" and content["is_completed"] is False
    scorm = content["scorm"]
    assert scorm["status"] == "READY" and scorm["completion_from_package"] is True
    launch_url = scorm["launch_url"]
    token = launch_url.split("/scorm/")[1].split("/")[0]

    # Launch page carries the shim, the learner's identity and the commit URL.
    page = await client.get(f"/scorm/{token}/index.html")
    assert page.status_code == 200
    seed = json.loads(re.search(r"window.__SWN_SCORM__=(\{.*?\});</script>", page.text).group(1))
    assert seed["mode"] == "learn" and seed["learnerId"] == str(state["learner"].id)
    assert seed["commitUrl"].endswith(f"/scorm/{token}/_lms/commit")
    assert seed["data"] == {}
    assert page.headers["cache-control"] == "no-store"

    # Relative assets resolve under the token, with Range support for audio seeking.
    audio = await client.get(f"/scorm/{token}/assets/audio/1-01.mp3")
    assert audio.status_code == 200 and audio.headers["content-type"].startswith("audio/mpeg")
    assert len(audio.content) == 1024
    partial = await client.get(f"/scorm/{token}/assets/audio/1-01.mp3", headers={"Range": "bytes=0-9"})
    assert partial.status_code == 206 and len(partial.content) == 10
    assert partial.headers["content-range"] == "bytes 0-9/1024"
    assert (await client.get(f"/scorm/{token}/%2e%2e/secrets")).status_code == 404
    assert (await client.get(f"/scorm/{token}/missing.js")).status_code == 404
    assert (await client.get(f"/scorm/{token}x/index.html")).status_code == 403

    # The package commits a bookmark + suspend data: saved, not yet complete.
    result = ok(
        await client.post(
            f"/scorm/{token}/_lms/commit",
            json={
                "session_id": "sess-1", "session_seconds": 40,
                "data": {
                    "cmi.core.lesson_status": "incomplete", "cmi.core.lesson_location": "0.2",
                    "cmi.suspend_data": '{"d":["0.0","0.1"]}', "cmi.core.session_time": "00:00:40",
                },
            },
        )
    )
    assert result["is_completed"] is False and result["lesson_status"] == "incomplete"
    assert result["total_time_seconds"] == 40

    # Re-launch resumes from the saved data (session-only keys dropped) and
    # reports total time so far.
    content = ok(await client.get(f"/learning/courses/{cid}/items/{item_id}", headers=lh))
    assert content["scorm"]["progress"]["lesson_location"] == "0.2"
    token2 = content["scorm"]["launch_url"].split("/scorm/")[1].split("/")[0]
    page = await client.get(f"/scorm/{token2}/index.html")
    seed = json.loads(re.search(r"window.__SWN_SCORM__=(\{.*?\});</script>", page.text).group(1))
    assert seed["data"]["cmi.suspend_data"] == '{"d":["0.0","0.1"]}'
    assert "cmi.core.session_time" not in seed["data"]
    assert seed["totalTime"] == "0000:00:40"

    # Second session: more time accrues on top, and completion marks the item done.
    result = ok(
        await client.post(
            f"/scorm/{token2}/_lms/commit",
            json={
                "session_id": "sess-2", "session_seconds": 20,
                "data": {"cmi.core.lesson_status": "completed", "cmi.core.score.raw": "90"},
            },
        )
    )
    assert result["is_completed"] is True and result["total_time_seconds"] == 60
    content = ok(await client.get(f"/learning/courses/{cid}/items/{item_id}", headers=lh))
    assert content["is_completed"] is True
    assert content["scorm"]["progress"]["score_raw"] == 90.0
    curriculum = ok(await client.get(f"/learning/courses/{cid}/curriculum", headers=lh))
    assert curriculum["progress_percent"] == 100 and curriculum["sections"][0]["items"][0]["is_completed"] is True


async def test_replacing_the_package_and_completion_rule(client, state, fake_s3):
    cid, item_id, admin_h = state["course_id"], state["item_id"], state["admin_h"]
    creds = ok(
        await client.post(f"/courses/items/{item_id}/scorm/refresh-upload?file_name=v2.zip", headers=admin_h)
    )
    manage = ok(await client.get(f"/courses/manage/{cid}", headers=admin_h))
    assert manage["sections"][0]["items"][0]["scorm"]["status"] == "PENDING"

    # A broken upload is reported, not silently accepted.
    fake_s3.put_object(Bucket="x", Key=creds["storage_key"], Body=b"not a zip", ContentType="application/zip")
    broken = await client.post(f"/courses/items/{item_id}/scorm/finalize", json={}, headers=admin_h)
    assert broken.status_code == 400 and "zip" in broken.text.lower()
    manage = ok(await client.get(f"/courses/manage/{cid}", headers=admin_h))
    pkg = manage["sections"][0]["items"][0]["scorm"]
    assert pkg["status"] == "FAILED" and pkg["error_message"]

    fake_s3.put_object(Bucket="x", Key=creds["storage_key"], Body=make_package_zip("v2"), ContentType="application/zip")
    ok(await client.post(f"/courses/items/{item_id}/scorm/finalize", json={}, headers=admin_h))

    ok(await client.patch(f"/courses/items/{item_id}", json={"scorm_completion_from_package": False}, headers=admin_h))
    manage = ok(await client.get(f"/courses/manage/{cid}", headers=admin_h))
    assert manage["sections"][0]["items"][0]["scorm"]["completion_from_package"] is False

    # Governance plumbing sees the package (snapshot + draft copy helpers import cleanly).
    from app.core.database import AsyncSessionLocal
    from app.modules.course.entity import Course
    from app.modules.governance.tree import build_normalized_tree

    async with AsyncSessionLocal() as session:
        course = await session.get(Course, uuid.UUID(cid))
        tree = await build_normalized_tree(session, course)
    node = tree["sections"][0]["items"][0]
    assert node["item_type"] == "SCORM" and node["scorm"]["launch_path"] == "index.html"
