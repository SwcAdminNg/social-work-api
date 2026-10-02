"""End-to-end content governance flow against a real (disposable) database.

One long scenario, in order, because each step builds on the last - exactly
how SWCL staff would use it: author -> reviewers -> publisher -> learners,
then a change to a live course, then a rollback, then moderated essay marking.
"""

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
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
    return response.json()


@pytest.fixture(autouse=True)
def governance_on(monkeypatch):
    monkeypatch.setattr(settings, "content_governance_enabled", True)


@pytest.fixture(scope="module")
def state():
    return {}


async def grant(client, admin_h, user, role, course_id=None):
    body = {"user_id": str(user.id), "role": role}
    if course_id:
        body["course_id"] = course_id
    return ok(await client.post("/admin/staff-roles", json=body, headers=admin_h), 201)


async def test_setup_staff(client, make_user, state):
    admin, admin_h = await make_user("Ada", UserTypeEnum.ADMIN)
    author, author_h = await make_user("Ike", UserTypeEnum.INSTRUCTOR)
    academic, academic_h = await make_user("Amaka")
    moderator, moderator_h = await make_user("Musa")
    qa, qa_h = await make_user("Queen")
    lead, lead_h = await make_user("Lola")
    hol, hol_h = await make_user("Halima")
    learner, learner_h = await make_user("Lerato")

    await grant(client, admin_h, academic, "ACADEMIC_REVIEWER")
    await grant(client, admin_h, moderator, "ASSESSMENT_MODERATOR")
    await grant(client, admin_h, qa, "QA_REVIEWER")
    await grant(client, admin_h, lead, "COURSE_LEAD")
    await grant(client, admin_h, hol, "HEAD_OF_LEARNING")
    # Academic reviewer also holds QA, to prove one person can't sign off twice.
    await grant(client, admin_h, academic, "QA_REVIEWER")

    perms = ok(await client.get("/governance/me/permissions", headers=hol_h))
    assert "FINAL_APPROVAL" in perms["permissions"] and "PUBLISH_CONTENT" not in perms["permissions"]
    admin_perms = ok(await client.get("/governance/me/permissions", headers=admin_h))
    assert "PUBLISH_CONTENT" in admin_perms["permissions"] and "ACADEMIC_REVIEW" not in admin_perms["permissions"]

    state.update(
        admin_h=admin_h, author=author, author_h=author_h, academic=academic, academic_h=academic_h,
        moderator_h=moderator_h, qa_h=qa_h, lead=lead, lead_h=lead_h, hol_h=hol_h, learner=learner,
        learner_h=learner_h, admin=admin,
    )


async def test_new_course_goes_through_full_high_risk_review(client, state):
    h = state["author_h"]
    course = ok(
        await client.post(
            "/courses",
            json={
                "title": "Child Protection Essentials", "description": "Safeguarding basics", "level": "BEGINNER",
                "category": "TEACHING_ACADEMICS", "what_you_will_learn": ["Recognise abuse"],
            },
            headers=h,
        ),
        201,
    )
    cid = course["id"]
    section = ok(await client.post(f"/courses/{cid}/sections", json={"title": "Module 1"}, headers=h), 201)
    link = ok(
        await client.post(
            f"/courses/{cid}/sections/{section['id']}/items",
            json={"title": "Read the guidance", "item_type": "LINKS", "url": "https://example.org/guidance"},
            headers=h,
        ),
        201,
    )
    quiz = ok(
        await client.post(
            f"/courses/{cid}/sections/{section['id']}/items",
            json={"title": "Knowledge check", "item_type": "ASSESSMENT", "assessment_type": "QUIZ", "order_index": 1},
            headers=h,
        ),
        201,
    )
    question = ok(
        await client.post(
            f"/courses/items/{quiz['id']}/quiz/questions",
            json={"text": "Who is responsible for safeguarding?", "options": [
                {"text": "Everyone", "is_correct": True}, {"text": "Only managers", "is_correct": False, "order_index": 1},
            ]},
            headers=h,
        ),
        201,
    )
    state.update(course_id=cid, section_id=section["id"], link_id=link["id"], quiz_id=quiz["id"], question=question)

    # The old publish toggle can't bypass review any more.
    fail(await client.patch(f"/courses/{cid}/publish?is_published=true", headers=state["admin_h"]), 409)

    gov = ok(await client.get(f"/courses/{cid}/governance", headers=h))
    assert gov["lifecycle"] == "DRAFT" and gov["open_revision"]["kind"] == "INITIAL"
    rid = gov["open_revision"]["id"]
    state["initial_revision"] = rid

    detail = ok(
        await client.post(f"/governance/revisions/{rid}/submit", json={"change_summary": "New course"}, headers=h)
    )
    assert detail["effective_risk"] == "HIGH"
    assert detail["required_stages"] == [
        "ACADEMIC_REVIEW", "ASSESSMENT_MODERATION", "QA_REVIEW", "COURSE_LEAD_APPROVAL", "FINAL_APPROVAL",
    ]
    assert detail["status"] == "SUBMITTED_FOR_REVIEW"
    assert detail["proposed_version_label"] == "1.0"

    # The author can't approve their own work; neither can the platform admin.
    fail(await client.post(f"/governance/revisions/{rid}/decision", json={"decision": "APPROVED"}, headers=h), 403)
    fail(await client.post(f"/governance/revisions/{rid}/decision", json={"decision": "APPROVED"}, headers=state["admin_h"]), 403)

    inbox = ok(await client.get("/governance/approval-centre?view=awaiting_me", headers=state["academic_h"]))
    assert any(row["id"] == rid for row in inbox)
    assert not ok(await client.get("/governance/approval-centre?view=awaiting_me", headers=state["qa_h"]))

    ok(await client.post(f"/governance/revisions/{rid}/claim", headers=state["academic_h"]))
    detail = ok(await client.post(
        f"/governance/revisions/{rid}/decision", json={"decision": "APPROVED", "comment": "Accurate"},
        headers=state["academic_h"],
    ))
    assert detail["status"] == "ACADEMICALLY_APPROVED" and detail["current_stage"] == "ASSESSMENT_MODERATION"

    ok(await client.post(f"/governance/revisions/{rid}/decision", json={
        "decision": "APPROVED_WITH_MINOR_CHANGES", "conditions": ["Add feedback to the question"],
    }, headers=state["moderator_h"]))
    detail = ok(await client.get(f"/governance/revisions/{rid}", headers=state["qa_h"]))
    assert detail["open_conditions"][0]["text"] == "Add feedback to the question"

    # Same person, second stage: blocked by separation of duties.
    fail(await client.post(
        f"/governance/revisions/{rid}/decision", json={"decision": "APPROVED"}, headers=state["academic_h"]
    ), 403, "already approved another stage")

    ok(await client.post(f"/governance/revisions/{rid}/decision", json={"decision": "APPROVED"}, headers=state["qa_h"]))
    detail = ok(await client.post(
        f"/governance/revisions/{rid}/decision", json={"decision": "APPROVED"}, headers=state["lead_h"]
    ))
    assert detail["status"] == "FINAL_APPROVAL_REQUIRED"

    # Learners can't enrol before publication.
    fail(await client.post(f"/learning/courses/{cid}/enroll", headers=state["learner_h"]), 404)

    detail = ok(await client.post(f"/governance/revisions/{rid}/decision", json={"decision": "APPROVED"}, headers=state["hol_h"]))
    assert detail["status"] == "READY_TO_PUBLISH"

    ready = ok(await client.get("/governance/approval-centre?view=ready_to_publish", headers=state["admin_h"]))
    assert [r["id"] for r in ready] == [rid]
    fail(await client.post(f"/governance/revisions/{rid}/publish", headers=state["lead_h"]), 403)
    detail = ok(await client.post(f"/governance/revisions/{rid}/publish", headers=state["admin_h"]))
    assert detail["status"] == "PUBLISHED"

    versions = ok(await client.get(f"/courses/{cid}/versions", headers=h))
    assert [v["label"] for v in versions] == ["1.0"] and versions[0]["has_snapshot"]
    assert {r["name"] for r in versions[0]["reviewers"]} >= {"Amaka Test", "Musa Test", "Queen Test", "Lola Test", "Halima Test"}


async def test_learner_progress_on_published_course(client, state):
    cid, lh = state["course_id"], state["learner_h"]
    ok(await client.post(f"/learning/courses/{cid}/enroll", headers=lh))
    ok(await client.post(f"/learning/courses/{cid}/items/{state['link_id']}/complete", headers=lh))
    q = state["question"]
    correct = next(o["id"] for o in q["options"] if o["is_correct"])
    result = ok(await client.post(
        f"/learning/courses/{cid}/items/{state['quiz_id']}/quiz/submit", json={"answers": {q["id"]: [correct]}}, headers=lh
    ))
    assert result["passed"] is True
    curriculum = ok(await client.get(f"/learning/courses/{cid}/curriculum", headers=lh))
    assert curriculum["is_completed"] is True


async def test_editing_a_live_course_uses_a_hidden_working_copy(client, state):
    cid, h, lh = state["course_id"], state["author_h"], state["learner_h"]
    q = state["question"]
    wrong = next(o for o in q["options"] if not o["is_correct"])

    # Edit through *live* ids - the API maps them onto the working copy.
    ok(await client.patch(f"/courses/items/{state['link_id']}", json={"title": "Read the 2026 guidance"}, headers=h))
    ok(await client.patch(f"/courses/quiz/options/{wrong['id']}", json={"is_correct": True}, headers=h))
    added = ok(await client.post(
        f"/courses/{cid}/sections/{state['section_id']}/items",
        json={"title": "Case study", "item_type": "LINKS", "url": "https://example.org/case", "order_index": 2},
        headers=h,
    ), 201)
    ok(await client.patch(f"/courses/{cid}", json={"description": "Safeguarding basics, updated", "price": 0}, headers=h))

    # Learners still see the published content...
    curriculum = ok(await client.get(f"/learning/courses/{cid}/curriculum", headers=lh))
    titles = [i["title"] for s in curriculum["sections"] for i in s["items"]]
    assert titles == ["Read the guidance", "Knowledge check"]
    assert curriculum["is_completed"] is True
    fail(await client.get(f"/learning/courses/{cid}/items/{added['id']}", headers=lh), 404)

    # ...while the manage view shows the working copy by default.
    manage = ok(await client.get(f"/courses/manage/{cid}", headers=h))
    assert manage["governance"]["layer"] == "draft"
    assert manage["description"] == "Safeguarding basics, updated"
    draft_titles = [i["title"] for s in manage["sections"] for i in s["items"]]
    assert draft_titles == ["Read the 2026 guidance", "Knowledge check", "Case study"]
    live_view = ok(await client.get(f"/courses/manage/{cid}?layer=live", headers=h))
    assert [i["title"] for s in live_view["sections"] for i in s["items"]] == ["Read the guidance", "Knowledge check"]

    rid = manage["governance"]["open_revision"]["id"]
    state["change_revision"] = rid
    diff = ok(await client.get(f"/governance/revisions/{rid}/diff", headers=h))
    assert diff["computed_risk"] == "HIGH"  # a correct answer changed
    ops = {(c["entity"], c["op"]) for c in diff["changes"]}
    assert ("item", "ADDED") in ops and ("option", "MODIFIED") in ops and ("course", "MODIFIED") in ops

    detail = ok(await client.post(f"/governance/revisions/{rid}/submit", json={"change_summary": "2026 refresh"}, headers=h))
    assert detail["proposed_version_label"] == "2.0"
    # Content is frozen while under review.
    fail(await client.patch(f"/courses/items/{state['link_id']}", json={"title": "x"}, headers=h), 409)

    # Returned for revision: back to the author with history kept.
    ok(await client.post(f"/governance/revisions/{rid}/decision", json={
        "decision": "RETURNED_FOR_REVISION", "comment": "Cite the 2026 statutory guidance",
    }, headers=state["academic_h"]))
    returned = ok(await client.get("/governance/approval-centre?view=returned_to_me", headers=h))
    assert [r["id"] for r in returned] == [rid]
    ok(await client.patch(f"/courses/items/{added['id']}", json={"title": "Case study (2026 guidance)"}, headers=h))
    detail = ok(await client.post(f"/governance/revisions/{rid}/submit", json={"change_summary": "2026 refresh, cited"}, headers=h))
    assert detail["round"] == 2 and detail["status"] == "SUBMITTED_FOR_REVIEW"
    assert any(d["decision"] == "RETURNED_FOR_REVISION" for d in detail["decisions"])

    # Head of Learning force-approves with a recorded justification.
    fail(await client.post(f"/governance/revisions/{rid}/force-approve", json={"justification": "short"}, headers=state["hol_h"]), 422)
    detail = ok(await client.post(f"/governance/revisions/{rid}/force-approve", json={
        "justification": "Statutory guidance changed; must be live before term starts",
    }, headers=state["hol_h"]))
    assert detail["status"] == "READY_TO_PUBLISH"

    ok(await client.post(f"/governance/revisions/{rid}/publish", headers=state["admin_h"]))
    state["added_item_id"] = added["id"]


async def test_publish_merges_in_place_and_keeps_learner_history(client, state):
    from app.modules.course.entity import CourseItem, CourseSection
    from app.modules.course.content_entity import CourseQuizOption
    from app.modules.learning.entity import QuizAttempt, UserItemProgress

    cid, lh = state["course_id"], state["learner_h"]
    curriculum = ok(await client.get(f"/learning/courses/{cid}/curriculum", headers=lh))
    items = [i for s in curriculum["sections"] for i in s["items"]]
    assert [i["title"] for i in items] == ["Read the 2026 guidance", "Knowledge check", "Case study (2026 guidance)"]
    # Same ids as before: progress stayed attached.
    assert items[0]["id"] == state["link_id"] and items[0]["is_completed"] is True
    assert items[1]["id"] == state["quiz_id"] and items[1]["is_completed"] is True
    assert items[2]["id"] == state["added_item_id"]  # a promoted draft keeps its id
    # A new item means the learner is no longer complete.
    assert curriculum["is_completed"] is False

    async with AsyncSessionLocal() as s:
        option_ids = {str(o["id"]) for o in state["question"]["options"]}
        options = (await s.execute(select(CourseQuizOption).where(CourseQuizOption.question_id == state["question"]["id"]))).scalars().all()
        assert {str(o.id) for o in options if o.deleted_at is None} == option_ids
        assert all(o.is_correct for o in options)  # the flipped option merged onto the same row
        drafts = (await s.execute(
            select(func.count(CourseItem.id)).where(CourseItem.revision_id.is_not(None)).execution_options(include_drafts=True)
        )).scalar_one()
        assert drafts == 0
        attempts = (await s.execute(select(func.count(QuizAttempt.id)).where(QuizAttempt.item_id == state["quiz_id"]))).scalar_one()
        assert attempts == 1

    versions = ok(await client.get(f"/courses/{cid}/versions", headers=state["author_h"]))
    assert [v["label"] for v in versions] == ["2.0", "1.0"]
    state["v1_id"] = versions[1]["id"]


async def test_rollback_requires_independent_final_approval(client, state):
    cid = state["course_id"]
    fail(await client.post(f"/courses/{cid}/versions/{state['v1_id']}/rollback", json={}, headers=state["author_h"]), 403)
    detail = ok(await client.post(
        f"/courses/{cid}/versions/{state['v1_id']}/rollback", json={"reason": "2026 guidance withdrawn"},
        headers=state["lead_h"],
    ), 201)
    assert detail["kind"] == "ROLLBACK" and detail["required_stages"] == ["FINAL_APPROVAL"]
    rid = detail["id"]
    # The initiator is a contributor, so needs someone else's final approval.
    ok(await client.post(f"/governance/revisions/{rid}/decision", json={"decision": "APPROVED"}, headers=state["hol_h"]))
    detail = ok(await client.post(f"/governance/revisions/{rid}/publish", headers=state["admin_h"]))
    assert detail["proposed_version_label"] == "2.1"

    curriculum = ok(await client.get(f"/learning/courses/{cid}/curriculum", headers=state["learner_h"]))
    items = [i for s in curriculum["sections"] for i in s["items"]]
    assert [i["title"] for i in items] == ["Read the guidance", "Knowledge check"]
    assert [i["id"] for i in items] == [state["link_id"], state["quiz_id"]]
    assert curriculum["is_completed"] is True  # restored progress counts again


async def test_low_risk_fix_uses_quick_approval(client, state):
    cid, h = state["course_id"], state["author_h"]
    ok(await client.patch(f"/courses/items/{state['link_id']}", json={"title": "Read the guidance (updated link)"}, headers=h))
    gov = ok(await client.get(f"/courses/{cid}/governance", headers=h))
    rid = gov["open_revision"]["id"]
    detail = ok(await client.post(f"/governance/revisions/{rid}/submit", json={"change_summary": "Fix typo"}, headers=h))
    assert detail["effective_risk"] == "LOW" and detail["required_stages"] == ["QUICK_APPROVAL"]
    # A reviewer escalates it - the full path is inserted.
    detail = ok(await client.post(f"/governance/revisions/{rid}/decision", json={
        "decision": "ESCALATED", "escalate_to": "MEDIUM", "comment": "Link points at a new policy document",
    }, headers=state["qa_h"]))
    assert detail["current_stage"] == "ACADEMIC_REVIEW"
    assert detail["effective_risk"] == "MEDIUM"


async def test_audit_trail_records_every_decision(client, state):
    rows = ok(await client.get(f"/governance/audit?course_id={state['course_id']}&page_size=100", headers=state["admin_h"]))
    actions = {r["action"] for r in rows}
    assert {"SUBMITTED", "DECISION_APPROVED", "DECISION_RETURNED_FOR_REVISION", "FORCE_APPROVED", "PUBLISHED",
            "DECISION_ESCALATED", "REVISION_OPENED"} <= actions
    async with AsyncSessionLocal() as s:
        from sqlalchemy import text

        with pytest.raises(Exception):
            await s.execute(text("UPDATE governance_audit_log SET action = 'TAMPERED'"))
        await s.rollback()


async def test_moderated_essay_marking(client, state, make_user):
    h, admin_h, hol_h = state["author_h"], state["admin_h"], state["hol_h"]
    course = ok(await client.post("/courses", json={
        "title": "Reflective Practice", "description": "Essay course", "level": "INTERMEDIATE",
        "category": "TEACHING_ACADEMICS",
    }, headers=h), 201)
    cid = course["id"]
    section = ok(await client.post(f"/courses/{cid}/sections", json={"title": "Module 1"}, headers=h), 201)
    essay = ok(await client.post(f"/courses/{cid}/sections/{section['id']}/items", json={
        "title": "Reflective essay", "item_type": "ASSESSMENT", "assessment_type": "ESSAY", "is_final_assessment": True,
        "essay_settings": {"question": "Reflect on a case", "description": "500 words", "submission_mode": "TEXT",
                           "pass_mark_percentage": 60, "max_attempts": 2},
    }, headers=h), 201)
    rid = ok(await client.get(f"/courses/{cid}/governance", headers=h))["open_revision"]["id"]
    ok(await client.post(f"/governance/revisions/{rid}/submit", json={"change_summary": "New course"}, headers=h))
    ok(await client.post(f"/governance/revisions/{rid}/force-approve", json={
        "justification": "Pilot course approved by academic board minute 12",
    }, headers=hol_h))
    ok(await client.post(f"/governance/revisions/{rid}/publish", headers=admin_h))

    learner, lh = state["learner"], state["learner_h"]
    ok(await client.post(f"/learning/courses/{cid}/enroll", headers=lh))
    ok(await client.post(f"/learning/courses/{cid}/items/{essay['id']}/essay/submit-text",
                         json={"content_text": "My reflection"}, headers=lh))

    mark = ok(await client.post(f"/courses/items/{essay['id']}/essay/submissions/{learner.id}/grade",
                                json={"score": 55, "feedback": "Good start", "recommendation": "FAIL"}, headers=h))
    item_view = ok(await client.get(f"/learning/courses/{cid}/items/{essay['id']}", headers=lh))
    assert item_view["essay_submission"]["is_graded"] is False  # draft marks stay invisible
    fail(await client.post(f"/learning/courses/{cid}/items/{essay['id']}/essay/submit-text",
                           json={"content_text": "edited"}, headers=lh), 400, "being marked")

    marks = ok(await client.get(f"/courses/items/{essay['id']}/essay-marks", headers=h))
    mark_id = marks[0]["id"]
    ok(await client.post(f"/essay-marks/{mark_id}/submit", headers=h))
    # The marker can't moderate their own mark.
    fail(await client.post(f"/essay-marks/{mark_id}/moderate", json={"action": "APPROVE"}, headers=h), 403)
    ok(await client.post(f"/essay-marks/{mark_id}/moderate", json={
        "action": "AMEND", "score": 65, "note": "Meets criteria 2 and 3",
    }, headers=state["moderator_h"]))
    ok(await client.post(f"/essay-marks/{mark_id}/dispute", json={"note": "Criterion 3 not evidenced"}, headers=h))
    fail(await client.post(f"/essay-marks/{mark_id}/approve", json={}, headers=state["lead_h"]), 400, "dispute")
    result = ok(await client.post(f"/essay-marks/{mark_id}/approve", json={
        "final_score": 62, "note": "Settled at 62", "publish": True,
    }, headers=state["lead_h"]))
    assert result["status"] == "PUBLISHED" and result["final_score"] == 62

    item_view = ok(await client.get(f"/learning/courses/{cid}/items/{essay['id']}", headers=lh))
    assert item_view["essay_submission"]["score"] == 62 and item_view["essay_submission"]["passed"] is True
    history = ok(await client.get(f"/courses/items/{essay['id']}/essay/submissions/{learner.id}/marks", headers=h))
    assert history[0]["disputed"] is True and history[0]["moderated_score"] == 65


async def test_governance_off_keeps_legacy_publishing(client, state, monkeypatch):
    monkeypatch.setattr(settings, "content_governance_enabled", False)
    h = state["author_h"]
    course = ok(await client.post("/courses", json={
        "title": "Legacy course", "description": "d", "level": "BEGINNER", "category": "TEACHING_ACADEMICS",
    }, headers=h), 201)
    cid = course["id"]
    section = ok(await client.post(f"/courses/{cid}/sections", json={"title": "M1"}, headers=h), 201)
    ok(await client.post(f"/courses/{cid}/sections/{section['id']}/items",
                         json={"title": "L1", "item_type": "LINKS", "url": "https://example.org"}, headers=h), 201)
    published = ok(await client.patch(f"/courses/{cid}/publish?is_published=true", headers=h))
    assert published["is_published"] is True and published["current_version_label"] == "1.0"
    # Edits apply live, as before.
    ok(await client.patch(f"/courses/{cid}", json={"title": "Legacy course v2"}, headers=h))
    manage = ok(await client.get(f"/courses/manage/{cid}", headers=h))
    assert manage["title"] == "Legacy course v2" and manage["governance"]["layer"] == "live"
