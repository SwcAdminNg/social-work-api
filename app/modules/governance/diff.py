"""Pure diff of two normalized course trees (see tree.py). No DB, no ORM - so
the reviewer diff view, risk classification and their tests all share it."""

from dataclasses import asdict, dataclass, field

ADDED = "ADDED"
REMOVED = "REMOVED"
MODIFIED = "MODIFIED"
MOVED = "MOVED"

# Fields compared per node type. Derived/processing fields (a video's encoding
# status, a document's detected size) are left out - they change without anyone
# editing content and would only add noise to a review.
COURSE_DIFF_FIELDS = (
    "title", "description", "prerequisite", "level", "category", "what_you_will_learn",
    "material_includes", "requirements", "certificate_enabled", "certificate_template_id",
)
SECTION_DIFF_FIELDS = ("title", "order_index", "guest_instructors")
ITEM_DIFF_FIELDS = ("title", "order_index", "is_preview", "estimated_minutes")
VIDEO_DIFF_FIELDS = ("bunny_video_guid",)
DOCUMENT_DIFF_FIELDS = ("storage_key", "file_name", "downloadable")
LINK_DIFF_FIELDS = ("url", "label", "description")
ASSESSMENT_DIFF_FIELDS = ("due_date", "is_final_assessment")
GROUP_SECTION_DIFF_FIELDS = ("title", "order_index", "questions_to_ask")
QUESTION_DIFF_FIELDS = ("text", "order_index", "allow_multiple_answers", "multi_answer_mode", "section_key")
OPTION_DIFF_FIELDS = ("text", "is_correct", "order_index")

ASSESSMENT_ENTITIES = frozenset({"assessment", "assessment_settings", "group_section", "question", "option"})


@dataclass
class Change:
    entity: str
    key: str
    op: str
    label: str
    fields: list[str] = field(default_factory=list)
    before: dict | None = None
    after: dict | None = None
    item_type: str | None = None

    @property
    def in_assessment(self) -> bool:
        return self.entity in ASSESSMENT_ENTITIES or (
            self.entity == "item" and self.item_type == "ASSESSMENT" and self.op in (ADDED, REMOVED)
        )

    def to_dict(self) -> dict:
        return asdict(self)


def _changed_fields(before: dict, after: dict, fields) -> list[str]:
    return [f for f in fields if before.get(f) != after.get(f)]


def _values(node: dict | None, fields) -> dict | None:
    if node is None:
        return None
    return {f: node.get(f) for f in fields}


def _diff_scalar_block(changes, entity, key, label, before, after, fields, item_type=None):
    """Diff an optional 1:1 child (video/document/link/settings)."""
    if before is None and after is None:
        return
    if before is None:
        changes.append(Change(entity, key, ADDED, label, list(fields), None, _values(after, fields), item_type))
    elif after is None:
        changes.append(Change(entity, key, REMOVED, label, list(fields), _values(before, fields), None, item_type))
    else:
        changed = _changed_fields(before, after, fields)
        if changed:
            changes.append(
                Change(entity, key, MODIFIED, label, changed, _values(before, changed), _values(after, changed), item_type)
            )


def _diff_keyed(changes, entity, before_list, after_list, fields, label_of):
    before = {n["key"]: n for n in before_list}
    after = {n["key"]: n for n in after_list}
    for key, node in after.items():
        if key not in before:
            changes.append(Change(entity, key, ADDED, label_of(node), list(fields), None, _values(node, fields)))
        else:
            changed = _changed_fields(before[key], node, fields)
            if changed:
                changes.append(
                    Change(entity, key, MODIFIED, label_of(node), changed, _values(before[key], changed), _values(node, changed))
                )
    for key, node in before.items():
        if key not in after:
            changes.append(Change(entity, key, REMOVED, label_of(node), list(fields), _values(node, fields), None))


def _diff_assessment(changes, item_key: str, label: str, before: dict | None, after: dict | None) -> None:
    if before is None and after is None:
        return
    if before is None or after is None:
        # A whole assessment appearing/disappearing is reported once, on the item.
        return
    changed = _changed_fields(before, after, ASSESSMENT_DIFF_FIELDS)
    if changed:
        changes.append(
            Change("assessment", item_key, MODIFIED, label, changed, _values(before, changed), _values(after, changed))
        )
    settings_fields = sorted(set(before.get("settings", {})) | set(after.get("settings", {})))
    _diff_scalar_block(
        changes, "assessment_settings", item_key, label, before.get("settings"), after.get("settings"), settings_fields
    )
    _diff_keyed(
        changes, "group_section", before.get("group_sections", []), after.get("group_sections", []),
        GROUP_SECTION_DIFF_FIELDS, lambda n: f"{label} › {n.get('title')}",
    )
    _diff_keyed(
        changes, "question", before.get("questions", []), after.get("questions", []),
        QUESTION_DIFF_FIELDS, lambda n: f"{label} › Q: {(n.get('text') or '')[:60]}",
    )
    before_q = {q["key"]: q for q in before.get("questions", [])}
    for question in after.get("questions", []):
        previous = before_q.get(question["key"])
        if previous is None:
            continue  # options of an added question are part of the ADDED question
        _diff_keyed(
            changes, "option", previous.get("options", []), question.get("options", []),
            OPTION_DIFF_FIELDS, lambda n, q=question: f"{label} › Q: {(q.get('text') or '')[:40]} › {n.get('text')}",
        )


def diff_trees(before: dict | None, after: dict) -> list[Change]:
    """Changes needed to turn `before` (normally the live tree) into `after`
    (normally the draft). `before=None` means a brand-new course: everything is
    ADDED."""
    before = before or {"course": {}, "sections": []}
    changes: list[Change] = []

    course_changed = _changed_fields(before.get("course", {}), after.get("course", {}), COURSE_DIFF_FIELDS)
    if course_changed:
        changes.append(
            Change(
                "course", "course", MODIFIED, "Course details", course_changed,
                _values(before.get("course", {}), course_changed), _values(after.get("course", {}), course_changed),
            )
        )

    _diff_keyed(
        changes, "section", before.get("sections", []), after.get("sections", []),
        SECTION_DIFF_FIELDS, lambda n: f"Module: {n.get('title')}",
    )

    def flatten(tree):
        result = {}
        for section in tree.get("sections", []):
            for item in section.get("items", []):
                result[item["key"]] = (section, item)
        return result

    before_items = flatten(before)
    after_items = flatten(after)

    for key, (section, item) in after_items.items():
        label = f"{section.get('title')} › {item.get('title')}"
        if key not in before_items:
            changes.append(
                Change("item", key, ADDED, label, list(ITEM_DIFF_FIELDS), None, _values(item, ITEM_DIFF_FIELDS), item["item_type"])
            )
            continue
        prev_section, prev_item = before_items[key]
        if prev_section["key"] != section["key"]:
            changes.append(
                Change(
                    "item", key, MOVED, label, ["section"],
                    {"section": prev_section.get("title")}, {"section": section.get("title")}, item["item_type"],
                )
            )
        changed = _changed_fields(prev_item, item, ITEM_DIFF_FIELDS)
        if changed:
            changes.append(
                Change("item", key, MODIFIED, label, changed, _values(prev_item, changed), _values(item, changed), item["item_type"])
            )
        _diff_scalar_block(changes, "video", key, label, prev_item.get("video"), item.get("video"), VIDEO_DIFF_FIELDS)
        _diff_scalar_block(
            changes, "document", key, label, prev_item.get("document"), item.get("document"), DOCUMENT_DIFF_FIELDS
        )
        _diff_scalar_block(changes, "link", key, label, prev_item.get("link"), item.get("link"), LINK_DIFF_FIELDS)
        _diff_assessment(changes, key, label, prev_item.get("assessment"), item.get("assessment"))

    for key, (section, item) in before_items.items():
        if key not in after_items:
            changes.append(
                Change(
                    "item", key, REMOVED, f"{section.get('title')} › {item.get('title')}", list(ITEM_DIFF_FIELDS),
                    _values(item, ITEM_DIFF_FIELDS), None, item["item_type"],
                )
            )
    return changes
