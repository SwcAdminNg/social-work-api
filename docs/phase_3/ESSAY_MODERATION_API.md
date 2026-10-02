# Essay Marking & Moderation — Staff API Reference

This document implements the framework's learner marking hierarchy (section 5.2): **Marker → Moderator → Lead Assessor / Course Lead**, with every mark kept as history. The rows appear in the [Approval Centre](./APPROVAL_CENTRE_API.md).

> ℹ️ The API strips null/absent fields from JSON output.

---

## User stories

- *As a marker*, I save a draft mark, send it to moderation, and contest an amendment if I disagree.
- *As a moderator*, I check another marker's work and approve it, amend it, or send it back. I can never moderate my own marking.
- *As a Course Lead / Lead Assessor*, I approve moderated results, settle disputes, and release results to learners, singly or in bulk.
- *As a learner*, I only ever see a final, approved result. My module only unlocks (or resets) on that result.

---

## 1. When moderation applies

`requires_moderation` is a setting on each essay assessment. It applies only while content governance is on (`CONTENT_GOVERNANCE_ENABLED=true`).
- **On:** marks go through the full path below.
- **Off:** grading works as before, in one step with optional publish. Each grade is still recorded in the mark history.

**Defaults:**
- It defaults to **on for final assessments**, since they gate modules and certificates.
- It defaults to off for other essays.

**Setting it:**
- When creating the item: `essay_settings.requires_moderation`.
- On an existing assessment: `PATCH /courses/items/{item_id}/assessment` with `{ "essay_settings": { "requires_moderation": true } }`.
- Changing it on a published course goes through content review, like any other assessment setting.

## 2. Statuses

`DRAFT_MARK → AWAITING_MODERATION → MODERATED → APPROVED → PUBLISHED`

Side paths:
- `RETURNED_TO_MARKER`: the moderator sent the mark back to the marker.
- `SUPERSEDED`: a later published mark replaced this one.

`UNDER_APPEAL` is reserved for the appeals phase.

Each learner's essay submission also carries the current `result_status`. While a mark is in progress (draft through approved), the learner **can't resubmit**; they get `400 "This essay is being marked…"`.

## 3. Endpoints

| Who | Method | Path | Body |
|---|---|---|---|
| Marker (MARK_ASSESSMENT) | `POST` | `/courses/items/{item_id}/essay/submissions/{user_id}/grade` | `{ "score", "feedback"?, "recommendation"?: "PASS"\|"FAIL", "submit_for_moderation"?: bool }`. On a moderated essay this creates or updates the draft mark and `is_published` is ignored. |
| Marker | `POST` | `/essay-marks/{mark_id}/submit` | Sends the draft (or returned) mark to moderation |
| Moderator (MODERATE_ASSESSMENT, not the marker) | `POST` | `/essay-marks/{mark_id}/moderate` | `{ "action": "APPROVE"\|"AMEND"\|"RETURN", "score"?, "feedback"?, "note"? }`. AMEND needs `score` and `note`; RETURN needs `note`. |
| Marker | `POST` | `/essay-marks/{mark_id}/dispute` | `{ "note" }`. Contests a moderated mark. |
| Approver (APPROVE_RESULTS, neither marker nor moderator) | `POST` | `/essay-marks/{mark_id}/approve` | `{ "final_score"?, "final_feedback"?, "note"?, "publish"?: bool }`. `final_score` is required to settle a dispute. |
| Approver | `POST` | `/courses/items/{item_id}/essay-marks/publish` | `{ "mark_ids": [...] }` or `{ "all_approved": true }` |
| Any of the above | `GET` | `/essay-marks/{mark_id}` | One mark, with its `available_actions` |
| Any of the above | `GET` | `/courses/items/{item_id}/essay-marks?status=AWAITING_MODERATION` | Queue for one essay |
| Any of the above | `GET` | `/courses/items/{item_id}/essay/submissions/{user_id}/marks` | Full history for one learner |

**Submission list:** `GET /courses/items/{item_id}/essay/submissions` now also returns `result_status`, `current_mark_id` and `working_score` per learner. `working_score` is the latest in-progress score: final if set, else moderated, else the marker's.

**Mark actions:** a mark's `available_actions` can include `EDIT`, `SUBMIT_FOR_MODERATION`, `MODERATE`, `DISPUTE`, `APPROVE` and `PUBLISH`.

**Who can open marking endpoints:** they accept anyone holding MARK_ASSESSMENT, MODERATE_ASSESSMENT or APPROVE_RESULTS for the course. A dedicated moderator doesn't need content-editing rights.

## 4. What publishing does

Only publication touches what the learner sees:
- It writes the final score and feedback onto the submission and marks it published.
- It counts the attempt.
- It logs `ESSAY_GRADED` to the learner's activity feed.
- For a **final assessment**, it runs the existing module/course mechanics: a pass unlocks the next module; running out of retries resets the module or course.

Before publication, draft and moderated marks can't unlock anything.

## 5. Notifications

| Type | Recipients |
|---|---|
| `MARKS_AWAITING_MODERATION` | Moderators |
| `MARKS_RETURNED` | The marker (returned or amended) |
| `MARKS_AWAITING_APPROVAL` | Approvers |
| `MARKS_DISPUTED` | Approvers |

Links point to `/dashboard/approval-centre/marks/{id}`. Every transition is written to the governance audit log (`entity_type=ESSAY_MARK`).
