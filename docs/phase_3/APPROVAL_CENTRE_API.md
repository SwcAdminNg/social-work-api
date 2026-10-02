# Approval Centre — Staff API Reference

The Approval Centre is the single inbox for everyone with a review or approval role (framework section 7). It lists **course revisions** and **essay marks** together. How revisions and decisions work is covered in [`CONTENT_GOVERNANCE_ADMIN_API.md`](./CONTENT_GOVERNANCE_ADMIN_API.md); marks are covered in [`ESSAY_MODERATION_API.md`](./ESSAY_MODERATION_API.md).

> ℹ️ The API strips null/absent fields from JSON output.

---

## User stories

- *As a reviewer*, I open one screen and see exactly what's waiting for **me**: only items I'm allowed to decide, never my own work.
- *As an author*, I see what was **returned to me** and why.
- *As a Course Lead*, I see what's **overdue** on my courses so I can chase or reassign it.
- *As a Platform Administrator*, I see what's **ready to publish**.

---

## 1. The inbox

`GET /governance/approval-centre?view={view}&kind={kind?}&course_id={id?}&page=&page_size=` (*paginated*)

Available to anyone holding a content, review, marking or publishing permission.

| `view` | Shows |
|---|---|
| `awaiting_me` (default) | Revision stages and marks you can decide now: you hold the permission, it's assigned to you or unassigned, and separation of duties allows it |
| `returned_to_me` | Revisions returned to you as a contributor; marks returned to you as the marker |
| `overdue` | Past-due stages you can decide, plus (for Course Leads / Head of Learning) everything overdue on courses they lead |
| `ready_to_publish` | Fully approved revisions (needs PUBLISH_CONTENT); approved marks awaiting release (needs APPROVE_RESULTS) |
| `recently_approved` | Approvals in the last 30 days that you made, or that were made on your work |
| `recently_rejected` | Returns and rejections in the last 30 days, same scope |
| `my_drafts` | Your open drafts and draft marks |

`kind=COURSE_REVISION` or `kind=ESSAY_MARK` limits the list to one type. Open views are sorted with overdue items first, then by soonest due date.

A row matches the framework's table: **Item, Type, Submitted by, Current stage, Reviewer, Due date, Action**.

```json
{
  "kind": "COURSE_REVISION",
  "id": "7c0...",
  "item_title": "Module 3 › Child Protection",
  "item_type": "Lesson",
  "course_id": "4f42...", "course_title": "Child Protection Essentials",
  "submitted_by": { "id": "...", "name": "Ike Okafor" },
  "current_stage": "ACADEMIC_REVIEW",
  "status": "SUBMITTED_FOR_REVIEW",
  "reviewer": { "id": "...", "name": "Dr Amaka" },
  "due_at": "2026-10-07T09:00:00Z", "is_overdue": false,
  "risk": "MEDIUM", "version_label": "1.2",
  "available_actions": ["CLAIM", "APPROVE", "APPROVE_WITH_MINOR_CHANGES", "RETURN_FOR_REVISION", "REJECT", "ESCALATE"]
}
```

**`item_type` values:**
- Revisions:
  - `Course`: a new course.
  - `Lesson`: changes confined to one lesson.
  - `Assessment`: assessment-only changes.
  - `Course update`: anything broader.
  - `Rollback` or `Reinstatement`.
- Marks: `Essay mark` or `Essay mark (disputed)`.

**Opening a row:**
- For `COURSE_REVISION` rows, use `id` with `GET /governance/revisions/{id}`.
- For `ESSAY_MARK` rows, use `GET /essay-marks/{id}`.

**Recent views:** in `recently_*` views, `decision` holds the decision and `reviewer` the person who made it.

### 1.1 Tab badges

`GET /governance/approval-centre/counts` returns `{ awaiting_me, returned_to_me, overdue, ready_to_publish }`.

---

## 2. The review screen (recommended layout)

1. **Header:** call `GET /governance/revisions/{id}`. It returns the title, `status`, `current_stage`, risk with `risk_reasons`, `proposed_version_label`, `change_summary`/`reason`, and the stage timeline from `stages` (including `is_overdue` and who decided each).
2. **What changed:** call `GET /governance/revisions/{id}/diff`. Group changes by `label` and badge each with its `risk`.
3. **Preview:** call `GET /governance/revisions/{id}/preview` to see the course exactly as learners will.
4. **Conditions:** show `open_conditions` from the previous stage's "approve with minor changes", which this reviewer should confirm.
5. **Discussion:** load comments and evidence (see the governance doc, §4). Anchor comments to a section, item or question using the diff `key`.
6. **Decision bar:** show buttons from `available_actions`. If the list contains no decision actions, show `blocked_reason`, e.g. *"You contributed to this revision, so you can't approve any stage of it"*.

| Button | Call |
|---|---|
| Claim | `POST /governance/revisions/{id}/claim` |
| Approve / Approve with minor changes / Return / Reject / Escalate | `POST /governance/revisions/{id}/decision` |
| Assign reviewer | `POST /governance/revisions/{id}/assign` |
| Force approve (Head of Learning) | `POST /governance/revisions/{id}/force-approve` |
| Publish (Platform Admin) | `POST /governance/revisions/{id}/publish` |

Every action returns the updated revision detail, so re-render from the response.

## 3. Due dates

Every stage gets `due_at` set to its start time plus `REVIEW_SLA_DAYS`, a server setting that defaults to 5. A Course Lead can change it when assigning. Automated reminders and escalation are a later phase.
