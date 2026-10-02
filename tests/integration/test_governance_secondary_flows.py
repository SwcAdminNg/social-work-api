"""The less-travelled governance paths: assignment, discussion, risk override,
withdraw/discard, rejection, archive/reinstate and the inbox counts."""

import pytest

from app.core.config import settings
from app.modules.user.entity import UserTypeEnum

pytestmark = pytest.mark.asyncio(loop_scope="session")


def ok(response, status: int | None = None):
    assert response.status_code < 300 if status is None else response.status_code == status, (
        response.status_code, response.text,
    )
    return response.json().get("data")


def fail(response, status: int):
    assert response.status_code == status, (response.status_code, response.text)


@pytest.fixture(autouse=True)
def governance_on(monkeypatch):
    monkeypatch.setattr(settings, "content_governance_enabled", True)


@pytest.fixture(scope="module")
def ctx():
    return {}


async def test_setup(client, make_user, ctx):
    admin, admin_h = await make_user("Root", UserTypeEnum.ADMIN)
    author, author_h = await make_user("Writer", UserTypeEnum.INSTRUCTOR)
    reviewer, reviewer_h = await make_user("Reviewer")
    reviewer2, reviewer2_h = await make_user("Reviewer2")
    lead, lead_h = await make_user("Lead")
    hol, hol_h = await make_user("Head")
    for user, role in ((reviewer, "ACADEMIC_REVIEWER"), (reviewer2, "ACADEMIC_REVIEWER"), (reviewer2, "QA_REVIEWER"),
                       (lead, "COURSE_LEAD"), (hol, "HEAD_OF_LEARNING")):
        ok(await client.post("/admin/staff-roles", json={"user_id": str(user.id), "role": role}, headers=admin_h), 201)

    course = ok(await client.post("/courses", json={
        "title": "Ethics in Practice", "description": "d", "level": "BEGINNER", "category": "TEACHING_ACADEMICS",
    }, headers=author_h), 201)
    section = ok(await client.post(f"/courses/{course['id']}/sections", json={"title": "M1"}, headers=author_h), 201)
    item = ok(await client.post(f"/courses/{course['id']}/sections/{section['id']}/items",
                                json={"title": "Codes of ethics", "item_type": "LINKS", "url": "https://example.org"},
                                headers=author_h), 201)
    ctx.update(admin_h=admin_h, author_h=author_h, reviewer=reviewer, reviewer_h=reviewer_h, reviewer2=reviewer2,
               reviewer2_h=reviewer2_h, lead_h=lead_h, hol_h=hol_h, course_id=course["id"], item_id=item["id"],
               section_id=section["id"])


async def test_withdraw_and_discard_initial(client, ctx):
    h = ctx["author_h"]
    rid = ok(await client.get(f"/courses/{ctx['course_id']}/governance", headers=h))["open_revision"]["id"]
    ok(await client.post(f"/governance/revisions/{rid}/submit", json={"change_summary": "First draft"}, headers=h))
    detail = ok(await client.post(f"/governance/revisions/{rid}/withdraw", headers=h))
    assert detail["status"] == "DRAFT" and detail["is_editable"]
    detail = ok(await client.post(f"/governance/revisions/{rid}/discard", headers=h))
    assert detail["status"] == "WITHDRAWN"
    # A fresh revision opens on the next edit.
    ok(await client.patch(f"/courses/items/{ctx['item_id']}", json={"title": "Codes of ethics (BASW)"}, headers=h))
    gov = ok(await client.get(f"/courses/{ctx['course_id']}/governance", headers=h))
    assert gov["open_revision"]["id"] != rid
    ctx["rid"] = gov["open_revision"]["id"]


async def test_assignment_comments_evidence_and_rejection(client, ctx):
    h, rid = ctx["author_h"], ctx["rid"]
    ok(await client.post(f"/governance/revisions/{rid}/submit", json={"change_summary": "Ready"}, headers=h))

    # A plain reviewer can't assign someone else; a Course Lead can.
    fail(await client.post(f"/governance/revisions/{rid}/assign",
                           json={"reviewer_id": str(ctx["reviewer2"].id)}, headers=ctx["reviewer_h"]), 403)
    detail = ok(await client.post(f"/governance/revisions/{rid}/assign",
                                  json={"reviewer_id": str(ctx["reviewer"].id)}, headers=ctx["lead_h"]))
    assert detail["status"] == "ACADEMIC_REVIEW"
    # Assigned to reviewer 1, so reviewer 2 is blocked.
    fail(await client.post(f"/governance/revisions/{rid}/decision", json={"decision": "APPROVED"},
                           headers=ctx["reviewer2_h"]), 403)
    inbox = ok(await client.get("/governance/approval-centre?view=awaiting_me", headers=ctx["reviewer2_h"]))
    assert all(row["id"] != rid for row in inbox)

    comment = ok(await client.post(f"/governance/revisions/{rid}/comments", json={
        "body": "Please cite the 2021 code", "anchor_type": "item", "anchor_id": ctx["item_id"],
    }, headers=ctx["reviewer_h"]), 201)
    ok(await client.post(f"/governance/revisions/{rid}/comments", json={
        "body": "Done", "parent_id": comment["id"],
    }, headers=h), 201)
    resolved = ok(await client.patch(f"/governance/comments/{comment['id']}/resolve", headers=h))
    assert resolved["resolved_at"]
    ok(await client.post(f"/governance/revisions/{rid}/evidence/link",
                         json={"title": "BASW code", "url": "https://example.org/code"}, headers=ctx["reviewer_h"]), 201)
    assert len(ok(await client.get(f"/governance/revisions/{rid}/comments", headers=h))) == 2
    assert ok(await client.get(f"/governance/revisions/{rid}/evidence", headers=h))[0]["title"] == "BASW code"

    detail = ok(await client.post(f"/governance/revisions/{rid}/decision", json={
        "decision": "REJECTED", "comment": "Out of scope for this programme",
    }, headers=ctx["reviewer_h"]))
    assert detail["status"] == "REJECTED"
    rejected = ok(await client.get("/governance/approval-centre?view=recently_rejected", headers=h))
    assert any(row["id"] == rid and row["decision"] == "REJECTED" for row in rejected)


async def test_risk_override_then_publish_archive_reinstate(client, ctx):
    h = ctx["author_h"]
    ok(await client.patch(f"/courses/items/{ctx['item_id']}", json={"title": "Codes of ethics"}, headers=h))
    rid = ok(await client.get(f"/courses/{ctx['course_id']}/governance", headers=h))["open_revision"]["id"]
    detail = ok(await client.post(f"/governance/revisions/{rid}/submit", json={"change_summary": "New course"}, headers=h))
    assert detail["effective_risk"] == "HIGH"  # a new course

    detail = ok(await client.post(f"/governance/revisions/{rid}/risk", json={
        "level": "MEDIUM", "reason": "Pilot with no certificate; board agreed medium",
    }, headers=ctx["hol_h"]))
    assert detail["effective_risk"] == "MEDIUM"
    final = next(s for s in detail["stages"] if s["stage"] == "FINAL_APPROVAL" and s["round"] == detail["round"])
    assert final["status"] == "SKIPPED"

    counts = ok(await client.get("/governance/approval-centre/counts", headers=ctx["reviewer_h"]))
    assert counts["awaiting_me"] >= 1
    ok(await client.post(f"/governance/revisions/{rid}/decision", json={"decision": "APPROVED"}, headers=ctx["reviewer_h"]))
    ok(await client.post(f"/governance/revisions/{rid}/decision", json={"decision": "APPROVED"}, headers=ctx["reviewer2_h"]))
    detail = ok(await client.post(f"/governance/revisions/{rid}/decision", json={"decision": "APPROVED"}, headers=ctx["lead_h"]))
    assert detail["status"] == "READY_TO_PUBLISH"
    # Legacy toggle publishes a ready revision.
    published = ok(await client.patch(f"/courses/{ctx['course_id']}/publish?is_published=true", headers=ctx["admin_h"]))
    assert published["is_published"] is True and published["current_version_label"] == "1.0"

    fail(await client.post(f"/courses/{ctx['course_id']}/archive", json={}, headers=h), 403)
    archived = ok(await client.post(f"/courses/{ctx['course_id']}/archive", json={"reason": "Retired"}, headers=ctx["admin_h"]))
    assert archived["lifecycle"] == "ARCHIVED"
    fail(await client.patch(f"/courses/items/{ctx['item_id']}", json={"title": "x"}, headers=h), 409)

    detail = ok(await client.post(f"/courses/{ctx['course_id']}/reinstate", json={"reason": "Back by demand"},
                                  headers=ctx["admin_h"]), 201)
    assert detail["kind"] == "REINSTATE" and detail["required_stages"] == ["QUICK_APPROVAL"]
    ok(await client.post(f"/governance/revisions/{detail['id']}/decision", json={"decision": "APPROVED"}, headers=ctx["lead_h"]))
    detail = ok(await client.post(f"/governance/revisions/{detail['id']}/publish", headers=ctx["admin_h"]))
    assert detail["proposed_version_label"] == "1.1"
    gov = ok(await client.get(f"/courses/{ctx['course_id']}/governance", headers=h))
    assert gov["lifecycle"] == "PUBLISHED"
