import copy

from app.modules.governance.diff import ADDED, MODIFIED, MOVED, REMOVED, diff_trees
from app.modules.governance.enums import ReviewStageEnum, RevisionKindEnum, RiskFlagEnum, RiskLevelEnum
from app.modules.governance.risk import classify, next_version, resolve_required_stages

St = ReviewStageEnum
LOW, MEDIUM, HIGH = RiskLevelEnum.LOW, RiskLevelEnum.MEDIUM, RiskLevelEnum.HIGH


def quiz(key="q-item"):
    return {
        "id": "a1",
        "assessment_type": "QUIZ",
        "due_date": None,
        "is_final_assessment": False,
        "settings": {"max_attempts": 3, "pass_mark_percentage": 70, "show_result_to_student": True},
        "group_sections": [],
        "questions": [
            {
                "key": "question-1",
                "section_key": None,
                "text": "What is safeguarding?",
                "order_index": 0,
                "allow_multiple_answers": False,
                "multi_answer_mode": None,
                "options": [
                    {"key": "opt-1", "text": "Protecting people", "is_correct": True, "order_index": 0},
                    {"key": "opt-2", "text": "Paperwork", "is_correct": False, "order_index": 1},
                ],
            }
        ],
    }


def item(key, title, item_type="LINKS", **extra):
    node = {
        "key": key, "item_type": item_type, "title": title, "order_index": 0, "is_preview": False,
        "estimated_minutes": 10, "video": None, "document": None, "link": None, "live_session": None,
        "assessment": None,
    }
    if item_type == "LINKS":
        node["link"] = {"url": "https://example.org", "label": "Read", "description": None}
    node.update(extra)
    return node


def base_tree():
    return {
        "schema": 1,
        "course": {
            "title": "Child Protection", "description": "d", "prerequisite": None, "level": "BEGINNER",
            "category": "TEACHING_ACADEMICS", "what_you_will_learn": ["a"], "material_includes": [],
            "requirements": [], "certificate_enabled": False, "certificate_template_id": None,
        },
        "sections": [
            {"key": "s1", "title": "Module 1", "order_index": 0, "guest_instructors": [],
             "items": [item("i1", "Intro"), item("q1", "Quiz", "ASSESSMENT", assessment=quiz())]},
            {"key": "s2", "title": "Module 2", "order_index": 1, "guest_instructors": [], "items": [item("i2", "Reading")]},
        ],
    }


def changed(mutator):
    before = base_tree()
    after = copy.deepcopy(before)
    mutator(after)
    return diff_trees(before, after)


def test_identical_trees_have_no_changes():
    assert diff_trees(base_tree(), base_tree()) == []


def test_title_typo_is_low_risk_quick_approval():
    changes = changed(lambda t: t["sections"][0]["items"][0].update(title="Introduction"))
    assert [(c.entity, c.op, c.fields) for c in changes] == [("item", MODIFIED, ["title"])]
    risk = classify(changes, RevisionKindEnum.CHANGE)
    assert risk.computed == LOW
    assert resolve_required_stages(risk.effective, risk.touches_assessment, RevisionKindEnum.CHANGE) == [
        St.QUICK_APPROVAL
    ]


def test_new_lesson_is_medium_risk_full_path_without_final():
    changes = changed(lambda t: t["sections"][1]["items"].append(item("i3", "New case study")))
    risk = classify(changes, RevisionKindEnum.CHANGE)
    assert risk.computed == MEDIUM
    assert resolve_required_stages(risk.effective, risk.touches_assessment, RevisionKindEnum.CHANGE) == [
        St.ACADEMIC_REVIEW, St.QA_REVIEW, St.COURSE_LEAD_APPROVAL,
    ]


def test_pass_mark_change_is_high_risk_with_moderation():
    def mutate(t):
        t["sections"][0]["items"][1]["assessment"]["settings"]["pass_mark_percentage"] = 50

    changes = changed(mutate)
    assert changes[0].entity == "assessment_settings"
    risk = classify(changes, RevisionKindEnum.CHANGE)
    assert risk.computed == HIGH and risk.touches_assessment
    assert resolve_required_stages(risk.effective, risk.touches_assessment, RevisionKindEnum.CHANGE) == [
        St.ACADEMIC_REVIEW, St.ASSESSMENT_MODERATION, St.QA_REVIEW, St.COURSE_LEAD_APPROVAL, St.FINAL_APPROVAL,
    ]


def test_flipping_a_correct_answer_is_high_risk():
    def mutate(t):
        opts = t["sections"][0]["items"][1]["assessment"]["questions"][0]["options"]
        opts[0]["is_correct"], opts[1]["is_correct"] = False, True

    risk = classify(changed(mutate), RevisionKindEnum.CHANGE)
    assert risk.computed == HIGH


def test_question_text_edit_is_medium_and_needs_moderation():
    def mutate(t):
        t["sections"][0]["items"][1]["assessment"]["questions"][0]["text"] = "Define safeguarding."

    risk = classify(changed(mutate), RevisionKindEnum.CHANGE)
    assert risk.computed == MEDIUM and risk.touches_assessment


def test_reordering_questions_does_not_pull_in_moderator():
    def mutate(t):
        t["sections"][0]["items"][1]["assessment"]["questions"][0]["order_index"] = 5

    risk = classify(changed(mutate), RevisionKindEnum.CHANGE)
    assert risk.computed == LOW and not risk.touches_assessment


def test_moving_an_item_between_modules_is_detected():
    def mutate(t):
        t["sections"][1]["items"].append(t["sections"][0]["items"].pop(0))

    changes = changed(mutate)
    assert any(c.op == MOVED and c.key == "i1" for c in changes)
    assert classify(changes, RevisionKindEnum.CHANGE).computed == MEDIUM


def test_removing_an_assessment_is_high():
    changes = changed(lambda t: t["sections"][0]["items"].pop(1))
    assert [(c.entity, c.op) for c in changes] == [("item", REMOVED)]
    assert classify(changes, RevisionKindEnum.CHANGE).computed == HIGH


def test_learning_outcomes_and_certificates_are_high():
    risk = classify(changed(lambda t: t["course"].update(what_you_will_learn=["a", "b"])), RevisionKindEnum.CHANGE)
    assert risk.computed == HIGH
    risk = classify(changed(lambda t: t["course"].update(certificate_enabled=True)), RevisionKindEnum.CHANGE)
    assert risk.computed == HIGH


def test_flags_and_declared_risk_only_raise():
    changes = changed(lambda t: t["sections"][0]["items"][0].update(title="Introduction"))
    flagged = classify(changes, RevisionKindEnum.CHANGE, flags=[RiskFlagEnum.SAFEGUARDING])
    assert flagged.computed == LOW and flagged.effective == HIGH
    declared = classify(changes, RevisionKindEnum.CHANGE, declared=MEDIUM)
    assert declared.effective == MEDIUM


def test_new_course_and_rollback_routing():
    assert classify([], RevisionKindEnum.INITIAL).effective == HIGH
    assert resolve_required_stages(HIGH, False, RevisionKindEnum.ROLLBACK) == [St.FINAL_APPROVAL]


def test_new_course_diff_is_all_added():
    changes = diff_trees(None, base_tree())
    assert {c.op for c in changes} == {ADDED, MODIFIED}  # course details + added sections/items
    assert sum(1 for c in changes if c.entity == "item" and c.op == ADDED) == 3


def test_versioning_rules():
    assert next_version(None, None, HIGH, RevisionKindEnum.INITIAL) == (1, 0)
    assert next_version(1, 0, MEDIUM, RevisionKindEnum.CHANGE) == (1, 1)
    assert next_version(1, 1, LOW, RevisionKindEnum.CHANGE) == (1, 2)
    assert next_version(1, 2, HIGH, RevisionKindEnum.CHANGE) == (2, 0)
    assert next_version(2, 0, HIGH, RevisionKindEnum.ROLLBACK) == (2, 1)
