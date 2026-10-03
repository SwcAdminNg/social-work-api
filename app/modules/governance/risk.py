"""Risk classification and stage routing (framework sections 4 and 5.1). Pure."""

from dataclasses import dataclass, field

from app.modules.governance.diff import ADDED, MOVED, REMOVED, Change
from app.modules.governance.enums import (
    RISK_ORDER,
    ReviewStageEnum,
    RevisionKindEnum,
    RiskFlagEnum,
    RiskLevelEnum,
    max_risk,
)

LOW, MEDIUM, HIGH = RiskLevelEnum.LOW, RiskLevelEnum.MEDIUM, RiskLevelEnum.HIGH

# Field-level risk for MODIFIED changes, per entity. A field missing here is LOW.
FIELD_RISK: dict[str, dict[str, RiskLevelEnum]] = {
    "course": {
        # Learning outcomes and anything certificate-affecting are high risk.
        "what_you_will_learn": HIGH,
        "certificate_enabled": HIGH,
        "certificate_template_id": HIGH,
        "certificate_pass_mark_percentage": HIGH,
        "description": MEDIUM,
        "prerequisite": MEDIUM,
        "requirements": MEDIUM,
        "level": MEDIUM,
        "category": MEDIUM,
    },
    "video": {"bunny_video_guid": MEDIUM},  # a new video
    "document": {"storage_key": MEDIUM, "file_name": MEDIUM},  # a new reading
    "assessment": {"is_final_assessment": HIGH, "due_date": MEDIUM},
    "assessment_settings": {
        "pass_mark_percentage": HIGH,
        "max_attempts": HIGH,
        "time_limit_seconds": HIGH,
        "submission_mode": HIGH,
        "show_result_to_student": MEDIUM,
        "requires_moderation": MEDIUM,
        "question": MEDIUM,
        "description": MEDIUM,
    },
    "group_section": {"questions_to_ask": HIGH},
    "question": {"allow_multiple_answers": HIGH, "multi_answer_mode": HIGH, "section_key": HIGH, "text": MEDIUM},
    "option": {"is_correct": HIGH, "text": MEDIUM},
}

# Risk of a node being added or removed.
STRUCTURAL_RISK: dict[str, RiskLevelEnum] = {
    "section": MEDIUM,
    "item": MEDIUM,  # ASSESSMENT items are HIGH, handled below
    "video": MEDIUM,
    "document": MEDIUM,
    "link": LOW,
    "assessment_settings": HIGH,
    "group_section": HIGH,
    "question": HIGH,
    "option": HIGH,
}

_WORDS = {ADDED: "added", REMOVED: "removed", MOVED: "moved to another module"}


@dataclass
class RiskAssessment:
    computed: RiskLevelEnum
    effective: RiskLevelEnum
    reasons: list[str] = field(default_factory=list)
    touches_assessment: bool = False


def change_risk(change: Change) -> RiskLevelEnum:
    if change.op in (ADDED, REMOVED):
        if change.entity == "item" and change.item_type == "ASSESSMENT":
            return HIGH
        return STRUCTURAL_RISK.get(change.entity, MEDIUM)
    if change.op == MOVED:
        return MEDIUM
    rules = FIELD_RISK.get(change.entity, {})
    return max_risk(*(rules.get(f, LOW) for f in change.fields))


def describe(change: Change) -> str:
    if change.op in _WORDS:
        noun = "assessment" if change.entity == "item" and change.item_type == "ASSESSMENT" else change.entity.replace("_", " ")
        return f"{change.label}: {noun} {_WORDS[change.op]}"
    return f"{change.label}: {', '.join(f.replace('_', ' ') for f in change.fields)} changed"


def classify(
    changes: list[Change],
    kind: RevisionKindEnum,
    flags: list[RiskFlagEnum] | None = None,
    declared: RiskLevelEnum | None = None,
) -> RiskAssessment:
    """`computed` comes from the content; `effective` is what routing uses:
    max(computed, declared, flags). A submitter can raise risk, never lower it."""
    reasons: list[str] = []
    levels: list[RiskLevelEnum] = []

    if kind == RevisionKindEnum.INITIAL:
        levels.append(HIGH)
        reasons.append("HIGH · New course")
    elif kind == RevisionKindEnum.ROLLBACK:
        levels.append(HIGH)
        reasons.append("HIGH · Rollback to an earlier version")
    elif kind == RevisionKindEnum.REINSTATE:
        levels.append(LOW)
        reasons.append("LOW · Reinstating an archived course")

    touches_assessment = False
    for change in changes:
        level = change_risk(change)
        levels.append(level)
        reasons.append(f"{level.value} · {describe(change)}")
        # Only meaningful assessment changes pull in the moderator - reordering
        # questions shouldn't need a second academic opinion.
        if change.in_assessment and RISK_ORDER[level] >= RISK_ORDER[MEDIUM]:
            touches_assessment = True

    computed = max_risk(*levels)
    flag_level = HIGH if flags else None
    for flag in flags or []:
        reasons.append(f"HIGH · Flagged {RiskFlagEnum(flag).value.replace('_', ' ').lower()}")
    effective = max_risk(computed, declared, flag_level)

    # Highest-risk reasons first - that's what a reviewer wants to see.
    reasons.sort(key=lambda r: -RISK_ORDER[RiskLevelEnum(r.split(" ", 1)[0])])
    return RiskAssessment(computed, effective, reasons, touches_assessment)


def resolve_required_stages(
    effective: RiskLevelEnum, touches_assessment: bool, kind: RevisionKindEnum
) -> list[ReviewStageEnum]:
    """Framework section 4 routing, plus the assessment design path (5.1):
    any change touching an assessment adds the Assessment Moderator stage."""
    if kind == RevisionKindEnum.ROLLBACK:
        return [ReviewStageEnum.FINAL_APPROVAL]
    if effective == LOW:
        return [ReviewStageEnum.QUICK_APPROVAL]
    stages = [ReviewStageEnum.ACADEMIC_REVIEW]
    if touches_assessment:
        stages.append(ReviewStageEnum.ASSESSMENT_MODERATION)
    stages += [ReviewStageEnum.QA_REVIEW, ReviewStageEnum.COURSE_LEAD_APPROVAL]
    if effective == HIGH:
        stages.append(ReviewStageEnum.FINAL_APPROVAL)
    return stages


def next_version(
    current_major: int | None, current_minor: int | None, effective: RiskLevelEnum, kind: RevisionKindEnum
) -> tuple[int, int]:
    """1.0 initial; HIGH-risk (major) changes bump the major; anything else the
    minor. A rollback or reinstatement restores already-approved content, so it
    is recorded as a minor release (e.g. "2.1 - rollback to 1.3")."""
    if current_major is None:
        return 1, 0
    if effective == HIGH and kind not in (RevisionKindEnum.REINSTATE, RevisionKindEnum.ROLLBACK):
        return current_major + 1, 0
    return current_major, (current_minor or 0) + 1
