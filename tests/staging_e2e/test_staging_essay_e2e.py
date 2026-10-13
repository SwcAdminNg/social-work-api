"""End-to-end essay marking across every role.

Marker -> moderator -> lead assessor / course lead -> publication, including the
moderator returning a mark, an amendment, a dispute, a no-dispute straight
approval, a failed attempt followed by a resubmission, separation of duties at
every step, learner visibility, admin monitoring and the audit trail.
"""

import uuid

import pytest

from app.core.config import settings
from app.modules.user.entity import UserTypeEnum

pytestmark = pytest.mark.asyncio(loop_scope="session")


def ok(response, status: int | None = None):
    assert response.status_code < 300 if status is None else response.status_code == status, (
        response.status_code, response.text,
    )
    return response.json().get("data")


def fail(response, status: int, contains: str | None = None):
    assert response.status_code == status, (response.status_code, response.text)
    if contains:
        assert contains.lower() in response.text.lower(), response.text


@pytest.fixture(autouse=True)
def governance_on(monkeypatch):
    monkeypatch.setattr(settings, "content_governance_enabled", True)


@pytest.fixture(scope="module")
def s():
    return {}


async def grant(client, admin_h, user, role, course_id=None):
    body = {"user_id": str(user.id), "role": role}
    if course_id:
        body["course_id"] = course_id
    return ok(await client.post("/admin/staff-roles", json=body, headers=admin_h), 201)


async def inbox(client, headers, view, kind="ESSAY_MARK"):
    return ok(await client.get(f"/governance/approval-centre?view={view}&kind={kind}", headers=headers))


def ids(rows):
    return {r["id"] for r in rows}


async def learner_view(client, s, who):
    cid, item = s["course_id"], s["essay_id"]
    return ok(await client.get(f"/learning/courses/{cid}/items/{item}", headers=s[f"{who}_h"]))["essay_submission"]


async def test_01_staff_course_and_submissions(client, make_user, s):
    admin, admin_h = await make_user("Ada", UserTypeEnum.ADMIN)
    marker, marker_h = await make_user("Mark", UserTypeEnum.INSTRUCTOR)
    moderator, moderator_h = await make_user("Musa")
    assessor, assessor_h = await make_user("Asha")
    lead, lead_h = await make_user("Lola")
    qa, qa_h = await make_user("Queen")
    hol, hol_h = await make_user("Halima")
    learner_a, a_h = await make_user("Lerato")
    learner_b, b_h = await make_user("Bayo")
    outsider, outsider_h = await make_user("Otto", UserTypeEnum.INSTRUCTOR)

    await grant(client, admin_h, moderator, "ASSESSMENT_MODERATOR")
    await grant(client, admin_h, assessor, "LEAD_ASSESSOR")
    await grant(client, admin_h, lead, "COURSE_LEAD")
    await grant(client, admin_h, qa, "QA_REVIEWER")
    await grant(client, admin_h, hol, "HEAD_OF_LEARNING")

    course = ok(await client.post("/courses", json={
        "title": "Reflective Practice E2E", "description": "Essay course", "level": "INTERMEDIATE",
        "category": "TEACHING_ACADEMICS",
    }, headers=marker_h), 201)
    cid = course["id"]
    section = ok(await client.post(f"/courses/{cid}/sections", json={"title": "Module 1"}, headers=marker_h), 201)
    essay = ok(await client.post(f"/courses/{cid}/sections/{section['id']}/items", json={
        "title": "Reflective essay", "item_type": "ASSESSMENT", "assessment_type": "ESSAY", "is_final_assessment": True,
        "essay_settings": {
            "question": "Reflect on a case", "description": "500 words", "submission_mode": "TEXT",
            "pass_mark_percentage": 60, "max_attempts": 3,
        },
    }, headers=marker_h), 201)
    rid = ok(await client.get(f"/courses/{cid}/governance", headers=marker_h))["open_revision"]["id"]
    ok(await client.post(f"/governance/revisions/{rid}/submit", json={"change_summary": "New course"}, headers=marker_h))
    ok(await client.post(f"/governance/revisions/{rid}/force-approve", json={
        "justification": "Pilot course approved by the academic board",
    }, headers=hol_h))
    ok(await client.post(f"/governance/revisions/{rid}/publish", headers=admin_h))

    for headers in (a_h, b_h):
        ok(await client.post(f"/learning/courses/{cid}/enroll", headers=headers))
        ok(await client.post(
            f"/learning/courses/{cid}/items/{essay['id']}/essay/submit-text",
            json={"content_text": "My reflection on the case."}, headers=headers,
        ))

    s.update(
        course_id=cid, essay_id=essay["id"], admin_h=admin_h, marker=marker, marker_h=marker_h,
        moderator=moderator, moderator_h=moderator_h, assessor=assessor, assessor_h=assessor_h, lead=lead,
        lead_h=lead_h, qa_h=qa_h, hol_h=hol_h, learner_a=learner_a, a_h=a_h, learner_b=learner_b, b_h=b_h,
        outsider_h=outsider_h,
    )


async def test_02_only_markers_can_mark(client, s):
    cid, item = s["course_id"], s["essay_id"]
    body = {"score": 70, "feedback": "x", "recommendation": "PASS"}
    url = f"/courses/items/{item}/essay/submissions/{s['learner_a'].id}/grade"
    for who in ("a_h", "outsider_h", "qa_h", "moderator_h"):
        resp = await client.post(url, json=body, headers=s[who])
        assert resp.status_code in (401, 403, 404), (who, resp.status_code, resp.text)
    assert (await client.get(f"/courses/items/{item}/essay-marks", headers=s["a_h"])).status_code in (401, 403, 404)


async def test_03_draft_is_private_and_locks_the_submission(client, s):
    item = s["essay_id"]
    ok(await client.post(
        f"/courses/items/{item}/essay/submissions/{s['learner_a'].id}/grade",
        json={"score": 40, "feedback": "Needs depth", "recommendation": "FAIL"}, headers=s["marker_h"],
    ))
    sub = await learner_view(client, s, "a")
    assert sub["is_graded"] is False  # a draft mark never leaks
    fail(await client.post(
        f"/learning/courses/{s['course_id']}/items/{item}/essay/submit-text",
        json={"content_text": "edit"}, headers=s["a_h"],
    ), 400, "being marked")

    marks = ok(await client.get(f"/courses/items/{item}/essay-marks", headers=s["marker_h"]))
    mark = next(m for m in marks if m["learner"]["id"] == str(s["learner_a"].id))
    s["mark_a"] = mark["id"]
    assert mark["status"] == "DRAFT_MARK"
    assert s["mark_a"] in ids(await inbox(client, s["marker_h"], "my_drafts"))
    # Nobody else's queue has it yet.
    for who in ("moderator_h", "assessor_h", "lead_h"):
        assert s["mark_a"] not in ids(await inbox(client, s[who], "awaiting_me"))


async def test_04_send_to_moderation_and_separation_of_duties(client, s):
    mid = s["mark_a"]
    # Only the marker can send it.
    fail(await client.post(f"/essay-marks/{mid}/submit", headers=s["moderator_h"]), 403)
    ok(await client.post(f"/essay-marks/{mid}/submit", headers=s["marker_h"]))

    assert mid in ids(await inbox(client, s["moderator_h"], "awaiting_me"))
    assert mid not in ids(await inbox(client, s["qa_h"], "awaiting_me"))
    assert mid not in ids(await inbox(client, s["lead_h"], "awaiting_me"))
    assert mid in ids(await inbox(client, s["admin_h"], "all_open"))

    # Marker can't moderate own work; people without the permission can't either.
    fail(await client.post(f"/essay-marks/{mid}/moderate", json={"action": "APPROVE"}, headers=s["marker_h"]), 403)
    for who in ("qa_h", "assessor_h", "lead_h", "admin_h", "outsider_h"):
        resp = await client.post(f"/essay-marks/{mid}/moderate", json={"action": "APPROVE"}, headers=s[who])
        assert resp.status_code in (403, 404), (who, resp.status_code)
    # Already submitted: the marker can no longer re-grade under them.
    resp = await client.post(
        f"/courses/items/{s['essay_id']}/essay/submissions/{s['learner_a'].id}/grade",
        json={"score": 99}, headers=s["marker_h"],
    )
    assert resp.status_code == 409


async def test_05_moderator_returns_then_marker_remarks(client, s):
    mid = s["mark_a"]
    fail(await client.post(f"/essay-marks/{mid}/moderate", json={"action": "RETURN"}, headers=s["moderator_h"]), 400)
    returned = ok(await client.post(
        f"/essay-marks/{mid}/moderate", json={"action": "RETURN", "note": "Score doesn't match criterion 2"},
        headers=s["moderator_h"],
    ))
    assert returned["status"] == "RETURNED_TO_MARKER"
    assert mid in ids(await inbox(client, s["marker_h"], "returned_to_me"))
    assert mid not in ids(await inbox(client, s["moderator_h"], "awaiting_me"))

    ok(await client.post(
        f"/courses/items/{s['essay_id']}/essay/submissions/{s['learner_a'].id}/grade",
        json={"score": 58, "feedback": "Re-marked", "recommendation": "FAIL", "submit_for_moderation": True},
        headers=s["marker_h"],
    ))
    assert mid in ids(await inbox(client, s["moderator_h"], "awaiting_me"))


async def test_06_amend_dispute_and_approve_without_publishing(client, s):
    mid = s["mark_a"]
    fail(await client.post(f"/essay-marks/{mid}/moderate", json={"action": "AMEND", "note": "n"}, headers=s["moderator_h"]), 400)
    amended = ok(await client.post(
        f"/essay-marks/{mid}/moderate", json={"action": "AMEND", "score": 65, "note": "Criteria 2 and 3 are met"},
        headers=s["moderator_h"],
    ))
    assert amended["status"] == "MODERATED" and amended["moderated_score"] == 65

    # Approvers see it; the people who touched it do not get to approve.
    for who in ("assessor_h", "lead_h"):
        assert mid in ids(await inbox(client, s[who], "awaiting_me")), who
    assert mid not in ids(await inbox(client, s["moderator_h"], "awaiting_me"))
    fail(await client.post(f"/essay-marks/{mid}/approve", json={}, headers=s["moderator_h"]), 403)
    fail(await client.post(f"/essay-marks/{mid}/approve", json={}, headers=s["marker_h"]), 403)
    fail(await client.post(f"/essay-marks/{mid}/approve", json={}, headers=s["qa_h"]), 403)

    # Marker disputes; the approver must settle with a final score.
    fail(await client.post(f"/essay-marks/{mid}/dispute", json={"note": "no"}, headers=s["marker_h"]), 422)
    fail(await client.post(f"/essay-marks/{mid}/dispute", json={"note": "Criterion 3 not evidenced"}, headers=s["moderator_h"]), 403)
    ok(await client.post(f"/essay-marks/{mid}/dispute", json={"note": "Criterion 3 not evidenced"}, headers=s["marker_h"]))
    fail(await client.post(f"/essay-marks/{mid}/approve", json={}, headers=s["assessor_h"]), 400, "dispute")
    approved = ok(await client.post(
        f"/essay-marks/{mid}/approve", json={"final_score": 62, "note": "Settled at 62"}, headers=s["assessor_h"],
    ))
    assert approved["status"] == "APPROVED" and approved["final_score"] == 62

    # Approved is not published: the learner still sees nothing.
    assert (await learner_view(client, s, "a"))["is_graded"] is False
    assert mid in ids(await inbox(client, s["assessor_h"], "ready_to_publish"))
    assert mid in ids(await inbox(client, s["admin_h"], "all_open"))


async def test_07_publish_releases_the_result(client, s):
    mid, item = s["mark_a"], s["essay_id"]
    fail(await client.post(f"/courses/items/{item}/essay-marks/publish", json={"all_approved": True}, headers=s["qa_h"]), 403)
    fail(await client.post(f"/courses/items/{item}/essay-marks/publish", json={}, headers=s["lead_h"]), 400)
    out = ok(await client.post(
        f"/courses/items/{item}/essay-marks/publish", json={"mark_ids": [mid]}, headers=s["lead_h"]
    ))
    assert out["published"] == 1
    sub = await learner_view(client, s, "a")
    assert sub["is_graded"] is True and sub["score"] == 62 and sub["passed"] is True
    detail = ok(await client.get(f"/essay-marks/{mid}", headers=s["admin_h"]))
    assert detail["status"] == "PUBLISHED" and detail["disputed"] is True
    # Publishing twice is harmless.
    again = ok(await client.post(
        f"/courses/items/{item}/essay-marks/publish", json={"mark_ids": [mid]}, headers=s["lead_h"]
    ))
    assert again["published"] == 0


async def test_08_straight_approval_and_failed_attempt_with_resubmission(client, s):
    item, cid = s["essay_id"], s["course_id"]
    uid = s["learner_b"].id
    ok(await client.post(
        f"/courses/items/{item}/essay/submissions/{uid}/grade",
        json={"score": 45, "feedback": "Below the bar", "recommendation": "FAIL", "submit_for_moderation": True},
        headers=s["marker_h"],
    ))
    marks = ok(await client.get(f"/courses/items/{item}/essay-marks", headers=s["moderator_h"]))
    mid = next(m["id"] for m in marks if m["learner"]["id"] == str(uid))
    ok(await client.post(f"/essay-marks/{mid}/moderate", json={"action": "APPROVE"}, headers=s["moderator_h"]))
    result = ok(await client.post(
        f"/essay-marks/{mid}/approve", json={"publish": True, "note": "Agreed"}, headers=s["lead_h"]
    ))
    assert result["status"] == "PUBLISHED" and result["final_score"] == 45
    sub = await learner_view(client, s, "b")
    assert sub["score"] == 45 and sub["passed"] is False

    # Failed with attempts left: the learner resubmits and a fresh mark cycle starts.
    ok(await client.post(
        f"/learning/courses/{cid}/items/{item}/essay/submit-text",
        json={"content_text": "A much deeper second attempt."}, headers=s["b_h"],
    ))
    ok(await client.post(
        f"/courses/items/{item}/essay/submissions/{uid}/grade",
        json={"score": 78, "feedback": "Much better", "recommendation": "PASS", "submit_for_moderation": True},
        headers=s["marker_h"],
    ))
    history = ok(await client.get(f"/courses/items/{item}/essay/submissions/{uid}/marks", headers=s["marker_h"]))
    assert len(history) == 2
    attempts = sorted(m["attempt_no"] for m in history)
    assert attempts == [1, 2]
    s["mark_b2"] = next(m["id"] for m in history if m["attempt_no"] == 2)
    ok(await client.post(f"/essay-marks/{s['mark_b2']}/moderate", json={"action": "APPROVE"}, headers=s["moderator_h"]))
    ok(await client.post(f"/essay-marks/{s['mark_b2']}/approve", json={"publish": True}, headers=s["assessor_h"]))
    sub = await learner_view(client, s, "b")
    assert sub["score"] == 78 and sub["passed"] is True
    # The earlier attempt is kept as history, no longer the live result.
    history = ok(await client.get(f"/courses/items/{item}/essay/submissions/{uid}/marks", headers=s["marker_h"]))
    statuses = {m["attempt_no"]: m["status"] for m in history}
    assert statuses[2] == "PUBLISHED" and statuses[1] == "SUPERSEDED"


async def test_09_admin_monitoring_and_audit_trail(client, s):
    mid = s["mark_a"]
    decided = await inbox(client, s["admin_h"], "all_decided")
    assert mid in ids(decided) and s["mark_b2"] in ids(decided)
    fail(await client.get("/governance/approval-centre?view=all_decided&kind=ESSAY_MARK", headers=s["moderator_h"]), 403)

    # Marker's history view and the learner-facing result stay consistent.
    marker_done = await inbox(client, s["marker_h"], "recently_approved")
    assert mid in ids(marker_done)

    log = ok(await client.get(
        f"/governance/audit?entity_type=ESSAY_MARK&course_id={s['course_id']}&page_size=100", headers=s["admin_h"]
    ))
    actions = {e["action"] for e in log}
    assert {
        "MARK_SAVED", "SENT_TO_MODERATION", "MODERATION_RETURN", "MODERATION_AMEND", "MODERATION_DISPUTED",
        "RESULT_APPROVED", "RESULT_PUBLISHED",
    } <= actions, actions
    amend = next(e for e in log if e["action"] == "MODERATION_AMEND")
    assert amend["actor"]["name"] == "Musa Test" and amend["course_title"] == "Reflective Practice E2E"
    published = [e for e in log if e["action"] == "RESULT_PUBLISHED"]
    assert {e["actor"]["name"] for e in published} >= {"Lola Test", "Asha Test"}
    fail(await client.get("/governance/audit?entity_type=ESSAY_MARK", headers=s["marker_h"]), 403)
