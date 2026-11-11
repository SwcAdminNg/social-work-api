"""Retries of a scored quiz are reworded by AI and the version a learner saw is kept.

DeepSeek is replaced by a stand-in that prefixes every text with "Reworded:", so
the test checks the whole path - start, reload, submit, staff review - offline.
"""

import pytest

from app.core.config import settings
from app.modules.learning import quiz_paraphrase
from app.modules.user.entity import UserTypeEnum

pytestmark = pytest.mark.asyncio(loop_scope="session")


def ok(response, status: int | None = None):
    assert response.status_code < 300 if status is None else response.status_code == status, (
        response.status_code, response.text,
    )
    return response.json().get("data")


@pytest.fixture(autouse=True)
def fake_deepseek(monkeypatch):
    monkeypatch.setattr(settings, "content_governance_enabled", False)
    monkeypatch.setattr(settings, "quiz_retry_paraphrase_enabled", True)
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    calls = []

    async def reword(chunk, *, model, course_title, item_title):
        calls.append(len(chunk))
        return {
            "questions": [
                {
                    "id": q["id"],
                    "text": f"Reworded: {q['original_text']}",
                    "options": [{"id": o["id"], "text": f"Reworded: {o['original_text']}"} for o in q["options"]],
                }
                for q in chunk
            ]
        }

    monkeypatch.setattr(quiz_paraphrase, "_reword_chunk", reword)
    return calls


@pytest.fixture(scope="module")
def state():
    return {}


async def test_first_attempt_uses_the_written_quiz(client, make_user, state, fake_deepseek):
    admin, admin_h = await make_user("Ada", UserTypeEnum.ADMIN)
    learner, learner_h = await make_user("Lerato")
    outsider, outsider_h = await make_user("Otto", UserTypeEnum.INSTRUCTOR)

    course = ok(await client.post("/courses", json={
        "title": "Safeguarding Basics", "description": "Quiz course", "level": "BEGINNER",
        "category": "TEACHING_ACADEMICS", "what_you_will_learn": ["Safeguarding"],
    }, headers=admin_h), 201)
    cid = course["id"]
    section = ok(await client.post(f"/courses/{cid}/sections", json={"title": "Module 1"}, headers=admin_h), 201)
    quiz = ok(await client.post(f"/courses/{cid}/sections/{section['id']}/items", json={
        "title": "Safeguarding check", "item_type": "ASSESSMENT", "assessment_type": "QUIZ",
        "quiz_settings": {"max_attempts": 3, "pass_mark_percentage": 100},
    }, headers=admin_h), 201)
    question_ids = []
    for n in range(3):
        q = ok(await client.post(f"/courses/items/{quiz['id']}/quiz/questions", json={
            "text": f"Question {n}", "order_index": n,
            "options": [
                {"text": f"Right {n}", "is_correct": True, "order_index": 0},
                {"text": f"Wrong {n}a", "is_correct": False, "order_index": 1},
                {"text": f"Wrong {n}b", "is_correct": False, "order_index": 2},
            ],
        }, headers=admin_h), 201)
        question_ids.append(q["id"])
    ok(await client.patch(f"/courses/{cid}/publish?is_published=true", headers=admin_h))
    ok(await client.post(f"/learning/courses/{cid}/enroll", headers=learner_h))

    started = ok(await client.post(f"/learning/courses/{cid}/items/{quiz['id']}/quiz/start", headers=learner_h))
    assert "paraphrased" not in started
    assert [q["text"] for q in started["questions"]] == ["Question 0", "Question 1", "Question 2"]
    assert fake_deepseek == []

    # Answer the first question wrong so the learner fails and retries.
    answers = {}
    for q in started["questions"]:
        right = next(o for o in q["options"] if o["text"].startswith("Right"))
        wrong = next(o for o in q["options"] if o["text"].startswith("Wrong"))
        answers[q["id"]] = [wrong["id"] if q["text"] == "Question 0" else right["id"]]
    result = ok(await client.post(
        f"/learning/courses/{cid}/items/{quiz['id']}/quiz/submit", json={"answers": answers}, headers=learner_h
    ))
    assert result["passed"] is False

    state.update(
        cid=cid, quiz_id=quiz["id"], admin_h=admin_h, learner_h=learner_h, outsider_h=outsider_h,
        question_ids=question_ids,
    )


async def test_retry_is_reworded_and_stable_until_submit(client, state, fake_deepseek):
    cid, quiz_id, lh = state["cid"], state["quiz_id"], state["learner_h"]

    started = ok(await client.post(f"/learning/courses/{cid}/items/{quiz_id}/quiz/start", headers=lh))
    # Students aren't told: no flag, just the new wording.
    assert "paraphrased" not in started
    assert fake_deepseek == [3]
    assert all(q["text"].startswith("Reworded: ") for q in started["questions"])
    assert all(o["text"].startswith("Reworded: ") for q in started["questions"] for o in q["options"])
    assert {q["id"] for q in started["questions"]} == set(state["question_ids"])

    # Starting again or reloading the lesson shows the same version, without a new AI call.
    again = ok(await client.post(f"/learning/courses/{cid}/items/{quiz_id}/quiz/start", headers=lh))
    assert again["questions"] == started["questions"]
    content = ok(await client.get(f"/learning/courses/{cid}/items/{quiz_id}", headers=lh))
    assert "quiz_paraphrased" not in content
    assert [q["text"] for q in content["questions"]] == [q["text"] for q in started["questions"]]
    assert fake_deepseek == [3]

    # Same ids, so scoring is unchanged: picking every reworded right answer passes.
    answers = {
        q["id"]: [next(o["id"] for o in q["options"] if o["text"].startswith("Reworded: Right"))]
        for q in started["questions"]
    }
    result = ok(await client.post(
        f"/learning/courses/{cid}/items/{quiz_id}/quiz/submit", json={"answers": answers}, headers=lh
    ))
    assert result["passed"] is True and result["score"] == 100


async def test_staff_see_each_attempt_as_the_learner_saw_it(client, state):
    quiz_id = state["quiz_id"]
    rows = ok(await client.get(f"/courses/items/{quiz_id}/quiz/attempts", headers=state["admin_h"]))
    assert [r["attempt_number"] for r in rows] == [2, 1]
    retry, first = rows

    assert retry["paraphrased"] is True and retry["version_recorded"] is True
    assert retry["score"] == 100 and retry["passed"] is True
    q = retry["questions"][0]
    assert q["text"].startswith("Reworded: ") and not q["original_text"].startswith("Reworded")
    chosen = [o for o in q["options"] if o["selected"]]
    assert len(chosen) == 1 and chosen[0]["is_correct"] and q["earned"] == 1

    assert first["paraphrased"] is False
    q0 = next(q for q in first["questions"] if q["original_text"] == "Question 0")
    assert q0["text"] == "Question 0" and q0["earned"] == 0
    assert [o["is_correct"] for o in q0["options"] if o["selected"]] == [False]

    denied = await client.get(f"/courses/items/{quiz_id}/quiz/attempts", headers=state["outsider_h"])
    assert denied.status_code == 403, denied.text


async def test_ai_failure_still_gives_a_shuffled_quiz(client, state, monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("DeepSeek is down")

    monkeypatch.setattr(quiz_paraphrase, "_reword_chunk", broken)
    started = ok(await client.post(
        f"/learning/courses/{state['cid']}/items/{state['quiz_id']}/quiz/start", headers=state["learner_h"]
    ))
    assert sorted(q["text"] for q in started["questions"]) == ["Question 0", "Question 1", "Question 2"]


async def test_quiz_group_retry_is_reworded_and_reviewable(client, make_user, fake_deepseek):
    admin, admin_h = await make_user("Ada", UserTypeEnum.ADMIN)
    learner, lh = await make_user("Bayo")
    course = ok(await client.post("/courses", json={
        "title": "Case Work Exam", "description": "Group quiz", "level": "BEGINNER",
        "category": "TEACHING_ACADEMICS", "what_you_will_learn": ["Case work"],
    }, headers=admin_h), 201)
    cid = course["id"]
    section = ok(await client.post(f"/courses/{cid}/sections", json={"title": "Module 1"}, headers=admin_h), 201)
    group = ok(await client.post(f"/courses/{cid}/sections/{section['id']}/items", json={
        "title": "Case work exam", "item_type": "ASSESSMENT", "assessment_type": "QUIZ_GROUP",
        "quiz_group_settings": {"max_attempts": 3, "pass_mark_percentage": 50},
    }, headers=admin_h), 201)
    for title in ("Ethics", "Practice"):
        sec = ok(await client.post(
            f"/courses/items/{group['id']}/quiz-group/sections", json={"title": title}, headers=admin_h
        ), 201)
        ok(await client.post(f"/courses/quiz-group/sections/{sec['id']}/questions", json={
            "text": f"{title} question",
            "options": [
                {"text": f"{title} right", "is_correct": True, "order_index": 0},
                {"text": f"{title} wrong", "is_correct": False, "order_index": 1},
            ],
        }, headers=admin_h), 201)
    ok(await client.patch(f"/courses/{cid}/publish?is_published=true", headers=admin_h))
    ok(await client.post(f"/learning/courses/{cid}/enroll", headers=lh))
    base = f"/learning/courses/{cid}/items/{group['id']}/quiz-group"

    first = ok(await client.post(f"{base}/start", headers=lh))
    assert [q["text"] for s in first["sections"] for q in s["questions"]] == ["Ethics question", "Practice question"]
    ok(await client.post(f"{base}/submit", json={"attempt_id": first["attempt_id"], "answers": {}}, headers=lh))
    assert fake_deepseek == []

    retry = ok(await client.post(f"{base}/start", headers=lh))
    assert "paraphrased" not in retry
    texts = [q["text"] for s in retry["sections"] for q in s["questions"]]
    assert texts == ["Reworded: Ethics question", "Reworded: Practice question"]
    # A reload keeps the same reworded version.
    content = ok(await client.get(f"/learning/courses/{cid}/items/{group['id']}", headers=lh))
    assert [q["text"] for s in content["quiz_group"]["active_attempt"]["sections"] for q in s["questions"]] == texts

    answers = {
        q["id"]: [next(o["id"] for o in q["options"] if "right" in o["text"])]
        for s in retry["sections"] for q in s["questions"]
    }
    result = ok(await client.post(
        f"{base}/submit", json={"attempt_id": retry["attempt_id"], "answers": answers}, headers=lh
    ))
    assert result["passed"] is True

    rows = ok(await client.get(f"/courses/items/{group['id']}/quiz/attempts", headers=admin_h))
    latest = rows[0]
    assert latest["attempt_number"] == 2 and latest["paraphrased"] is True
    assert [q["section_title"] for q in latest["questions"]] == ["Ethics", "Practice"]
    assert all(q["earned"] == 1 for q in latest["questions"])
    assert rows[1]["paraphrased"] is False and all(q["earned"] == 0 for q in rows[1]["questions"])
