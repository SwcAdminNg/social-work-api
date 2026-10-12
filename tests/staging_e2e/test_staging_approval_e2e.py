"""End-to-end approval workflow across every staff role.

One scenario, in order. Covers: submitter-routed returns, return to the
previous stage's reviewer, return to the author, resubmission, admin-wide
monitoring, the audit trail, reviewer access to documents under review, and
the instructor-application acknowledgement email.
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


async def inbox(client, headers, view):
    return ok(await client.get(f"/governance/approval-centre?view={view}", headers=headers))


async def decide(client, rid, headers, decision, **extra):
    return ok(await client.post(
        f"/governance/revisions/{rid}/decision", json={"decision": decision, **extra}, headers=headers
    ))


async def test_01_staff_and_course(client, make_user, s):
    admin, admin_h = await make_user("Ada", UserTypeEnum.ADMIN)
    owner, owner_h = await make_user("Ike", UserTypeEnum.INSTRUCTOR)
    dev, dev_h = await make_user("Dev")
    academic, academic_h = await make_user("Amaka")
    moderator, moderator_h = await make_user("Musa")
    qa, qa_h = await make_user("Queen")
    lead, lead_h = await make_user("Lola")
    hol, hol_h = await make_user("Halima")
    assessor, assessor_h = await make_user("Asha")
    outsider, outsider_h = await make_user("Otto", UserTypeEnum.INSTRUCTOR)

    await grant(client, admin_h, academic, "ACADEMIC_REVIEWER")
    await grant(client, admin_h, moderator, "ASSESSMENT_MODERATOR")
    await grant(client, admin_h, qa, "QA_REVIEWER")
    await grant(client, admin_h, lead, "COURSE_LEAD")
    await grant(client, admin_h, hol, "HEAD_OF_LEARNING")
    await grant(client, admin_h, assessor, "LEAD_ASSESSOR")

    # Every role resolves to exactly the permissions the framework gives it.
    expected = {
        "academic": (academic_h, {"ACADEMIC_REVIEW"}),
        "moderator": (moderator_h, {"MODERATE_ASSESSMENT"}),
        "qa": (qa_h, {"QA_REVIEW"}),
        "lead": (lead_h, {"APPROVE_COURSE", "APPROVE_RESULTS", "EDIT_DRAFT_CONTENT", "SUBMIT_FOR_REVIEW"}),
        "hol": (hol_h, {"FINAL_APPROVAL", "FORCE_APPROVE", "APPROVE_RESULTS"}),
        "assessor": (assessor_h, {"APPROVE_RESULTS"}),
    }
    for name, (headers, perms) in expected.items():
        got = set(ok(await client.get("/governance/me/permissions", headers=headers))["permissions"])
        assert perms <= got, (name, got)
    admin_perms = set(ok(await client.get("/governance/me/permissions", headers=admin_h))["permissions"])
    assert {"PUBLISH_CONTENT", "MANAGE_STAFF_ROLES"} <= admin_perms and "ACADEMIC_REVIEW" not in admin_perms

    # Course + one uploaded document (view-only) + a quiz, by the owning instructor.
    course = ok(await client.post("/courses", json={
        "title": "Case Management Practice", "description": "Practice", "level": "BEGINNER",
        "category": "TEACHING_ACADEMICS", "what_you_will_learn": ["Manage cases"],
    }, headers=owner_h), 201)
    cid = course["id"]
    section = ok(await client.post(f"/courses/{cid}/sections", json={"title": "Module 1"}, headers=owner_h), 201)
    doc = ok(await client.post(f"/courses/{cid}/sections/{section['id']}/items", json={
        "title": "Case file template", "item_type": "DOCUMENT", "file_name": "template.pdf", "downloadable": False,
    }, headers=owner_h), 201)
    doc_id = doc["id"] if "id" in doc else doc["item"]["id"]
    ok(await client.post(f"/courses/items/{doc_id}/document/finalize", json={
        "mime_type": "application/pdf", "file_size_bytes": 1234,
    }, headers=owner_h))
    quiz = ok(await client.post(f"/courses/{cid}/sections/{section['id']}/items", json={
        "title": "Check", "item_type": "ASSESSMENT", "assessment_type": "QUIZ", "order_index": 1,
    }, headers=owner_h), 201)
    ok(await client.post(f"/courses/items/{quiz['id']}/quiz/questions", json={
        "text": "Who owns the case?", "options": [
            {"text": "The worker", "is_correct": True}, {"text": "Nobody", "is_correct": False, "order_index": 1},
        ],
    }, headers=owner_h), 201)

    # A content developer is scoped to this course.
    await grant(client, admin_h, dev, "CONTENT_DEVELOPER", cid)

    s.update(
        admin_h=admin_h, admin=admin, owner=owner, owner_h=owner_h, dev=dev, dev_h=dev_h, academic_h=academic_h,
        moderator_h=moderator_h, qa_h=qa_h, qa=qa, lead_h=lead_h, hol_h=hol_h, outsider_h=outsider_h,
        course_id=cid, doc_id=doc_id, section_id=section["id"],
    )


async def test_02_reviewer_can_open_unpublished_non_downloadable_document(client, s):
    cid = s["course_id"]
    rid = ok(await client.get(f"/courses/{cid}/governance", headers=s["owner_h"]))["open_revision"]["id"]
    s["rid"] = rid

    # Submitted by a content developer who never edited it: they are the submitter.
    detail = ok(await client.post(
        f"/governance/revisions/{rid}/submit", json={"change_summary": "New course"}, headers=s["dev_h"]
    ))
    assert detail["status"] == "SUBMITTED_FOR_REVIEW"
    assert detail["submitted_by"]["id"] == str(s["dev"].id)
    assert str(s["dev"].id) in {c["id"] for c in detail["contributors"]}

    # Reviewers (not the owner, not enrolled, course unpublished, file not downloadable) can open it.
    for key in ("academic_h", "qa_h", "lead_h", "hol_h", "admin_h"):
        data = ok(await client.get(f"/governance/revisions/{rid}/items/{s['doc_id']}/document", headers=s[key]))
        assert data["view_url"].startswith("http") and data["download_url"].startswith("http")
        assert data["file_name"] == "template.pdf"
    # ...but the learner-facing endpoint stays closed, and strangers get nothing.
    fail(await client.get(f"/governance/revisions/{rid}/items/{s['doc_id']}/document", headers=s["outsider_h"]), 403)
    fail(await client.get(f"/governance/revisions/{rid}/items/{uuid.uuid4()}/document", headers=s["academic_h"]), 404)


async def test_03_admin_sees_the_whole_workflow(client, s):
    rid = s["rid"]
    open_rows = await inbox(client, s["admin_h"], "all_open")
    assert rid in {r["id"] for r in open_rows}
    row = next(r for r in open_rows if r["id"] == rid)
    assert row["submitted_by"]["id"] == str(s["dev"].id)
    counts = ok(await client.get("/governance/approval-centre/counts", headers=s["admin_h"]))
    assert counts["all_open"] >= 1
    assert "all_open" not in ok(await client.get("/governance/approval-centre/counts", headers=s["qa_h"]))
    # Only admins may monitor everything.
    fail(await client.get("/governance/approval-centre?view=all_open", headers=s["qa_h"]), 403)
    fail(await client.get("/governance/approval-centre?view=all_decided", headers=s["owner_h"]), 403)
    # The admin still can't approve - monitoring isn't reviewing.
    fail(await client.post(
        f"/governance/revisions/{rid}/decision", json={"decision": "APPROVED"}, headers=s["admin_h"]
    ), 403)


async def test_04_course_lead_returns_to_the_previous_reviewer(client, s):
    rid = s["rid"]
    await decide(client, rid, s["academic_h"], "APPROVED", comment="Accurate")
    await decide(client, rid, s["moderator_h"], "APPROVED")
    detail = await decide(client, rid, s["qa_h"], "APPROVED", comment="Quality ok")
    assert detail["current_stage"] == "COURSE_LEAD_APPROVAL"
    assert detail["previous_reviewer"]["id"] == str(s["qa"].id) and detail["previous_stage"] == "QA_REVIEW"

    # A return needs a reason.
    fail(await client.post(
        f"/governance/revisions/{rid}/decision", json={"decision": "RETURNED_FOR_REVISION"}, headers=s["lead_h"]
    ), 400)
    detail = await decide(client, rid, s["lead_h"], "RETURNED_FOR_REVISION", comment="QA missed the glossary")
    # Same round, QA's stage reopened and assigned to them.
    assert detail["status"] == "QA_REVIEW" and detail["current_stage"] == "QA_REVIEW"

    awaiting_qa = await inbox(client, s["qa_h"], "awaiting_me")
    assert s["rid"] in {r["id"] for r in awaiting_qa}
    assert s["rid"] not in {r["id"] for r in await inbox(client, s["lead_h"], "awaiting_me")}
    # It has not gone to the author's side yet.
    assert s["rid"] not in {r["id"] for r in await inbox(client, s["dev_h"], "returned_to_me")}


async def test_05_qa_re_approves_then_lead_returns_to_the_author(client, s):
    rid = s["rid"]
    detail = await decide(client, rid, s["qa_h"], "APPROVED", comment="Glossary checked")
    assert detail["current_stage"] == "COURSE_LEAD_APPROVAL"
    assert rid in {r["id"] for r in await inbox(client, s["lead_h"], "awaiting_me")}

    detail = await decide(
        client, rid, s["lead_h"], "RETURNED_FOR_REVISION", comment="Needs a rewrite", return_to="AUTHOR"
    )
    assert detail["status"] == "RETURNED_FOR_REVISION" and detail["is_editable"] is True
    # Goes to the person who submitted it (and is visible to the owner who authored it).
    assert rid in {r["id"] for r in await inbox(client, s["dev_h"], "returned_to_me")}
    assert rid in {r["id"] for r in await inbox(client, s["owner_h"], "returned_to_me")}
    # Reviewers' queues are clear.
    for key in ("qa_h", "lead_h", "academic_h"):
        assert rid not in {r["id"] for r in await inbox(client, s[key], "awaiting_me")}


async def test_06_resubmit_and_complete_the_pipeline(client, s):
    rid = s["rid"]
    detail = ok(await client.post(
        f"/governance/revisions/{rid}/submit", json={"change_summary": "Rewritten"}, headers=s["dev_h"]
    ))
    assert detail["round"] == 2 and detail["status"] == "SUBMITTED_FOR_REVIEW"

    assert rid in {r["id"] for r in await inbox(client, s["academic_h"], "awaiting_me")}
    await decide(client, rid, s["academic_h"], "APPROVED")
    await decide(client, rid, s["moderator_h"], "APPROVED")
    await decide(client, rid, s["qa_h"], "APPROVED")
    detail = await decide(client, rid, s["lead_h"], "APPROVED")
    assert detail["status"] == "FINAL_APPROVAL_REQUIRED"
    detail = await decide(client, rid, s["hol_h"], "APPROVED")
    assert detail["status"] == "READY_TO_PUBLISH"

    assert rid in {r["id"] for r in await inbox(client, s["admin_h"], "ready_to_publish")}
    fail(await client.post(f"/governance/revisions/{rid}/publish", headers=s["lead_h"]), 403)
    detail = ok(await client.post(f"/governance/revisions/{rid}/publish", headers=s["admin_h"]))
    assert detail["status"] == "PUBLISHED"


async def test_07_admin_audit_trail_and_decision_history(client, s):
    rid = s["rid"]
    # Per-revision history carries who/what/why for every decision.
    detail = ok(await client.get(f"/governance/revisions/{rid}", headers=s["admin_h"]))
    returned = [d for d in detail["decisions"] if d["decision"] == "RETURNED_FOR_REVISION"]
    assert len(returned) == 2 and {d["actor"]["name"] for d in returned} == {"Lola Test"}
    assert all(d["comment"] for d in returned)

    # Global audit log: actor names, course title, action filter.
    log = ok(await client.get(f"/governance/audit?course_id={s['course_id']}&page_size=100", headers=s["admin_h"]))
    actions = {e["action"] for e in log}
    assert {"SUBMITTED", "DECISION_APPROVED", "DECISION_RETURNED_FOR_REVISION", "PUBLISHED"} <= actions
    assert all(e["course_title"] == "Case Management Practice" for e in log if e["course_id"])
    submitted = [e for e in log if e["action"] == "SUBMITTED"]
    assert {e["actor"]["name"] for e in submitted} == {"Dev Test"}
    returns = [e for e in log if e["action"] == "DECISION_RETURNED_FOR_REVISION"]
    assert any(e["metadata_json"] and e["metadata_json"].get("returned_to_stage") == "QA_REVIEW" for e in returns)

    only = ok(await client.get(
        f"/governance/audit?course_id={s['course_id']}&action=PUBLISHED", headers=s["admin_h"]
    ))
    assert only and {e["action"] for e in only} == {"PUBLISHED"}
    fail(await client.get("/governance/audit", headers=s["qa_h"]), 403)

    decided = await inbox(client, s["admin_h"], "all_decided")
    assert rid in {r["id"] for r in decided}
    assert rid not in {r["id"] for r in await inbox(client, s["admin_h"], "all_open")}


async def test_08_instructor_application_acknowledgement_email(client, monkeypatch):
    from app.core.email import email_service

    sent: list[tuple[str, str]] = []

    async def fake_received(to_email, first_name):
        sent.append((to_email, first_name))

    monkeypatch.setattr(email_service, "send_instructor_application_received_email", fake_received)
    email = f"applicant-{uuid.uuid4().hex[:8]}@mailinator.com"
    ok(await client.post("/instructor-applications", json={
        "first_name": "Ngozi", "last_name": "Eze", "email": email, "phone_number": "08000000000",
        "cv_file_name": "cv.pdf", "cv_content_type": "application/pdf",
    }), 201)
    assert sent == [(email, "Ngozi")]

    # A failing email never blocks the application.
    async def boom(*_a, **_k):
        raise RuntimeError("resend down")

    monkeypatch.setattr(email_service, "send_instructor_application_received_email", boom)
    ok(await client.post("/instructor-applications", json={
        "first_name": "Tunde", "last_name": "Ade", "email": f"applicant-{uuid.uuid4().hex[:8]}@mailinator.com",
        "phone_number": "08000000001", "cv_file_name": "cv.pdf",
    }), 201)
