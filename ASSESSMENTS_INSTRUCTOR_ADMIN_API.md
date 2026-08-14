# Assessments (Quiz & Essay) — Instructor/Admin API Reference

This document covers the **generic Assessment system**: curriculum items that used to be a
single hard-coded `QUIZ` item type are now a generic `ASSESSMENT` item type with a pluggable
`assessment_type` (`QUIZ` or `ESSAY` today; more types can be added later without another schema
change). This doc is scoped to **instructor/admin (management) endpoints only** — creating,
configuring, and grading assessments. A separate doc will cover the student-facing endpoints
(taking a quiz, submitting an essay) later.

Base URL prefix for everything below: `/courses`.

## Conventions

- **Auth**: every endpoint below requires `Authorization: Bearer <token>` for a user who is either
  `ADMIN`, or an `INSTRUCTOR` who owns the course the item belongs to. Endpoints keyed by `item_id`
  (not `course_id`) still enforce this — the API resolves `item → section → course` internally and
  403s if you don't own it.
- **Response envelope**: every endpoint returns `ApiResponse<T>`:
  ```json
  { "success": true, "message": "...", "data": { /* T, or omitted for 204-style responses */ } }
  ```
  List endpoints return `PaginatedResponse<T>` instead:
  ```json
  {
    "success": true,
    "message": "OK",
    "data": [ /* T[] */ ],
    "meta": { "page": 1, "page_size": 20, "total_items": 42, "total_pages": 3, "has_next": true, "has_previous": false }
  }
  ```
- **Null stripping**: the API strips null/absent fields from JSON output. If a field isn't present
  in a response, treat it as `null`/unset.
- **Errors**: standard `ApiErrorResponse` — `{ "success": false, "message": "...", "errors": [...] | null }`
  with the appropriate HTTP status (400, 403, 404, 422).

---

## 1. The mental model

```
CourseItem (item_type = ASSESSMENT)
  └── Assessment (assessment_type = QUIZ | ESSAY, + optional due_date)
        ├── QUIZ   → CourseQuizSettings (max_attempts, pass_mark_percentage, show_result_to_student)
        │            + Questions (each with Options)
        └── ESSAY  → CourseEssaySettings (question, description, submission_mode)
```

- `item_type` on a `CourseItem` is now `"VIDEO" | "DOCUMENT" | "ASSESSMENT"` (the old `"QUIZ"` value
  is gone — quizzes are `item_type: "ASSESSMENT"` + `assessment_type: "QUIZ"`).
- `due_date` is optional and lives at the assessment level, so it applies to both quiz and essay.
  Leave it `null`/omit it for "no deadline".
- Every place that used to return a `quiz` object on a course item now returns an `assessment`
  object instead (see §4).

---

## 2. Creating an assessment item

**`POST /courses/{course_id}/sections/{section_id}/items`**

This is the same endpoint used to create video/document items — pass `item_type: "ASSESSMENT"`
plus an `assessment_type` and the matching settings block.

### Request body — `CourseItemCreateDTO`

| Field | Type | Required | Notes |
|---|---|---|---|
| `title` | string (1-255) | yes | |
| `item_type` | `"VIDEO" \| "DOCUMENT" \| "ASSESSMENT"` | yes | Use `"ASSESSMENT"` for both quiz and essay. |
| `order_index` | int | no (default `0`) | |
| `is_preview` | bool | no (default `false`) | |
| `assessment_type` | `"QUIZ" \| "ESSAY"` | **required when `item_type = ASSESSMENT`** | 400 if missing. |
| `due_date` | ISO 8601 datetime \| null | no | Omit/`null` = no deadline. |
| `quiz_settings` | object \| null | no, only used when `assessment_type = QUIZ` | See below. Fully optional — all fields default. |
| `essay_settings` | object \| null | **required when `assessment_type = ESSAY`** | 400 if missing. |

`quiz_settings` (`CourseQuizSettingsInDTO` — all optional):

| Field | Type | Default | Notes |
|---|---|---|---|
| `max_attempts` | int ≥ 1 \| null | `null` (unlimited) | |
| `pass_mark_percentage` | int, 0-100 | `70` | This is a **percentage** — `40` means 40/100, not a raw score. |
| `show_result_to_student` | bool | `true` | If `false`, the student is told they submitted but never sees score/pass-fail/correct answers. |

`essay_settings` (`CourseEssaySettingsInDTO` — all required):

| Field | Type | Notes |
|---|---|---|
| `question` | string (min 1 char) | The essay prompt/title. |
| `description` | string (min 1 char) | Longer instructions shown to the student. |
| `submission_mode` | `"TEXT" \| "DOCUMENT"` | Locks how the student can answer — free text vs. file upload. |

### Example — create a QUIZ item

```http
POST /courses/{course_id}/sections/{section_id}/items
```
```json
{
  "title": "Module 1 Quiz",
  "item_type": "ASSESSMENT",
  "assessment_type": "QUIZ",
  "order_index": 3,
  "due_date": "2026-09-01T23:59:00Z",
  "quiz_settings": {
    "max_attempts": 3,
    "pass_mark_percentage": 40,
    "show_result_to_student": true
  }
}
```

`quiz_settings` can be omitted entirely to get unlimited attempts, a 70% pass mark, and visible
results — matching current defaults.

### Example — create an ESSAY item

```http
POST /courses/{course_id}/sections/{section_id}/items
```
```json
{
  "title": "Reflective Essay",
  "item_type": "ASSESSMENT",
  "assessment_type": "ESSAY",
  "essay_settings": {
    "question": "Describe a trauma-informed intervention you would use.",
    "description": "Write 500-800 words. Reference at least one framework covered in this module.",
    "submission_mode": "TEXT"
  }
}
```
No `due_date` given → this essay never locks based on a deadline (still locks once graded — see §6).

### Response — `201 Created`

```json
{
  "success": true,
  "message": "Item created successfully",
  "data": {
    "id": "b6e2a1f0-....",
    "created_at": "2026-08-14T10:00:00Z",
    "section_id": "....",
    "title": "Module 1 Quiz",
    "item_type": "ASSESSMENT",
    "order_index": 3,
    "is_preview": false
  }
}
```
(`video_upload`/`document_upload` fields also exist on this response shape but are only populated
for VIDEO/DOCUMENT items — irrelevant here.) Note the response does **not** echo the created
`assessment` object — fetch the course's manage detail (§4) or use the `item.id` with the
quiz-question/essay-grading endpoints below.

---

## 3. Updating assessment settings

**`PATCH /courses/items/{item_id}/assessment`**

Partial update — only send the fields you want to change. This is a single endpoint for both quiz
and essay; send `quiz_settings` or `essay_settings` matching the item's actual `assessment_type`
(sending the wrong one returns `400`).

### Request body — `CourseAssessmentUpdateDTO`

| Field | Type | Notes |
|---|---|---|
| `due_date` | ISO 8601 datetime \| null | Omit to leave unchanged. Send explicit `null` to **clear** an existing deadline. |
| `quiz_settings` | partial object \| null | Only valid if the item is a QUIZ. Any subset of `max_attempts`, `pass_mark_percentage`, `show_result_to_student`. |
| `essay_settings` | partial object \| null | Only valid if the item is an ESSAY. Any subset of `question`, `description`, `submission_mode`. |

### Examples

Change the pass mark and turn off attempt limits:
```json
{ "quiz_settings": { "pass_mark_percentage": 50, "max_attempts": null } }
```

Push the deadline back:
```json
{ "due_date": "2026-10-15T23:59:00Z" }
```

Remove the deadline entirely:
```json
{ "due_date": null }
```

Edit an essay prompt:
```json
{ "essay_settings": { "question": "Updated prompt text..." } }
```

### Response
```json
{ "success": true, "message": "Assessment settings updated successfully" }
```

---

## 4. Reading assessments (as part of course content)

Assessment items are returned inline wherever course content is returned — most importantly
**`GET /courses/manage/{id}`** (full curriculum tree for editing). Each `CourseItem` in
`sections[].items[]` now has an `assessment` field instead of the old `quiz` field:

### Quiz item shape (`CourseAssessmentManageDTO`, `assessment_type = "QUIZ"`)

```json
{
  "id": "assessment-uuid",
  "assessment_type": "QUIZ",
  "due_date": "2026-09-01T23:59:00Z",
  "quiz": {
    "max_attempts": 3,
    "pass_mark_percentage": 40,
    "show_result_to_student": true,
    "questions": [
      {
        "id": "question-uuid",
        "text": "Which of these are core principles of trauma-informed care?",
        "order_index": 0,
        "allow_multiple_answers": true,
        "multi_answer_mode": "OR",
        "options": [
          { "id": "opt-1", "text": "Safety", "order_index": 0, "is_correct": true },
          { "id": "opt-2", "text": "Trustworthiness", "order_index": 1, "is_correct": true },
          { "id": "opt-3", "text": "Punishment", "order_index": 2, "is_correct": false }
        ]
      }
    ]
  }
}
```
(`is_correct` on options is only present in this **manage** view — the student-facing public view
never exposes it.)

### Essay item shape (`assessment_type = "ESSAY"`)

```json
{
  "id": "assessment-uuid",
  "assessment_type": "ESSAY",
  "due_date": null,
  "essay": {
    "question": "Describe a trauma-informed intervention you would use.",
    "description": "Write 500-800 words. Reference at least one framework covered in this module.",
    "submission_mode": "TEXT"
  }
}
```

`quiz` and `essay` are mutually exclusive — only the one matching `assessment_type` is populated
(the other is omitted, per the null-stripping rule).

---

## 5. Quiz questions & options

These endpoints are unchanged in shape from before, with one addition: `multi_answer_mode`.

### 5.1 Grading semantics (so you configure questions correctly)

- **Single-answer question** (`allow_multiple_answers: false`): student must select exactly the
  correct option. All-or-nothing, worth 1 point.
- **Multi-answer, `multi_answer_mode: "AND"`**: student must select **exactly** the full correct
  set — every correct option ticked, zero incorrect ones ticked. All-or-nothing, worth 1 point.
- **Multi-answer, `multi_answer_mode: "OR"`** (default when omitted): **partial credit** —
  the question is worth `(number of correct options the student ticked) / (total correct options
  for that question)`, e.g. 2 out of 3 correct options ticked = 0.67 of a point.
- Every question is worth 1 point regardless of how many options it has. Overall quiz score =
  `(sum of question points / total questions) × 100`, compared against `pass_mark_percentage`.
- `multi_answer_mode` **must be omitted/`null`** when `allow_multiple_answers: false` — the API
  returns `400` if you set it on a single-answer question.

### 5.2 Add a question (with options)

**`POST /courses/items/{item_id}/quiz/questions`** — `item_id` is the **course item's** id (the
`CourseItem.id`, not the assessment id).

```json
{
  "text": "Which of these are core principles of trauma-informed care?",
  "order_index": 0,
  "allow_multiple_answers": true,
  "multi_answer_mode": "OR",
  "options": [
    { "text": "Safety", "is_correct": true, "order_index": 0 },
    { "text": "Trustworthiness", "is_correct": true, "order_index": 1 },
    { "text": "Punishment", "is_correct": false, "order_index": 2 }
  ]
}
```

Response (`201`) — full question with generated option IDs (`CourseQuizQuestionManageDTO`):
```json
{
  "success": true,
  "message": "Question created successfully",
  "data": {
    "id": "question-uuid",
    "text": "Which of these are core principles of trauma-informed care?",
    "order_index": 0,
    "allow_multiple_answers": true,
    "multi_answer_mode": "OR",
    "options": [
      { "id": "opt-1", "text": "Safety", "order_index": 0, "is_correct": true },
      { "id": "opt-2", "text": "Trustworthiness", "order_index": 1, "is_correct": true },
      { "id": "opt-3", "text": "Punishment", "order_index": 2, "is_correct": false }
    ]
  }
}
```

### 5.3 Update / delete a question

**`PATCH /courses/quiz/questions/{question_id}`** — partial update. Body: any subset of `text`,
`order_index`, `allow_multiple_answers`, `multi_answer_mode` (`QuizQuestionUpdateDTO`). If you flip
`allow_multiple_answers` to `false`, also clear `multi_answer_mode` (send `null`) or the update
call will reject it.

**`DELETE /courses/quiz/questions/{question_id}`** — soft-deletes the question (and its options
stop appearing in the question list; existing attempts that already reference it are unaffected).

### 5.4 Add / update / delete an option

**`POST /courses/quiz/questions/{question_id}/options`**
```json
{ "text": "Consistency", "is_correct": false, "order_index": 3 }
```

**`PATCH /courses/quiz/options/{option_id}`** — partial update: any subset of `text`, `is_correct`,
`order_index`.

**`DELETE /courses/quiz/options/{option_id}`** — soft-delete.

All four return either `201` + the created option, or `200` + `{ "success": true, "message": "..." }`
for update/delete, matching the pattern used elsewhere in this API.

---

## 6. Essay grading

### 6.1 List submissions for an essay item

**`GET /courses/items/{item_id}/essay/submissions?page=1&page_size=20`**

`item_id` is the course item's id. Returns one row per student who has submitted, most recent
first.

```json
{
  "success": true,
  "message": "OK",
  "data": [
    {
      "user_id": "student-uuid",
      "user_full_name": "Jane Student",
      "user_email": "jane@example.com",
      "content_text": "My essay answer...",
      "document_file_name": null,
      "document_download_url": null,
      "submitted_at": "2026-08-10T14:00:00Z",
      "score": null,
      "is_published": false,
      "feedback": null
    },
    {
      "user_id": "other-student-uuid",
      "user_full_name": "Sam Learner",
      "user_email": "sam@example.com",
      "content_text": null,
      "document_file_name": "essay.pdf",
      "document_download_url": "https://.../essay.pdf?X-Amz-...",
      "submitted_at": "2026-08-11T09:30:00Z",
      "score": 82.5,
      "is_published": true,
      "feedback": "Strong analysis, needs more citations."
    }
  ],
  "meta": { "page": 1, "page_size": 20, "total_items": 2, "total_pages": 1, "has_next": false, "has_previous": false }
}
```

- Only one of `content_text` / `document_file_name`+`document_download_url` is populated, matching
  the essay's `submission_mode`.
- `document_download_url` is a **freshly generated, short-lived presigned URL** every time you call
  this endpoint — don't cache it long-term.
- `score`/`is_published`/`feedback` reflect the current grading state, regardless of whether the
  student can see it yet (this is the instructor view — always visible to you).

### 6.2 Grade a submission

**`POST /courses/items/{item_id}/essay/submissions/{user_id}/grade`**

```json
{
  "score": 82.5,
  "feedback": "Strong analysis, needs more citations.",
  "is_published": true
}
```

| Field | Type | Notes |
|---|---|---|
| `score` | float, 0-100 | Required every call (this endpoint fully replaces the grade, it doesn't merge). |
| `feedback` | string \| null | Optional. |
| `is_published` | bool | Default `false`. Controls whether the **student** can see `score`/`feedback` — see student-facing doc for details. |

Response:
```json
{ "success": true, "message": "Essay graded successfully" }
```

Calling this again on the same `(item_id, user_id)` **overwrites** the previous grade (e.g. to
correct a score or flip `is_published`). `404` if the student hasn't submitted this essay yet.

**Important**: once a submission has a non-null `score`, the student can no longer resubmit/edit
their answer (enforced on the student-facing endpoints, not here) — grade only when you're ready to
lock it in. There's currently no "un-grade"/reset endpoint; if you need to reopen a submission for
resubmission, that requires a direct data fix for now.

---

## 7. Generic item management (unchanged, included for completeness)

These apply to assessment items the same way they apply to video/document items:

- **`PATCH /courses/items/{item_id}`** — update `title`/`order_index`/`is_preview` (`CourseItemUpdateDTO`).
- **`DELETE /courses/items/{item_id}`** — soft-delete the item (and its assessment/settings/questions
  go with it, but existing student attempts/submissions are preserved).
- **`PATCH /courses/{course_id}/sections/{section_id}/items/reorder`** — bulk reorder
  (`{ "items": [{ "id": "...", "order_index": 0 }, ...] }`).

---

## 8. Error responses you should handle

| Status | When |
|---|---|
| `400` | `item_type=ASSESSMENT` without `assessment_type`; `assessment_type=ESSAY` without `essay_settings`; `multi_answer_mode` set on a single-answer question; `quiz_settings`/`essay_settings` sent for the wrong assessment type on the settings-patch endpoint. |
| `403` | Current user is neither `ADMIN` nor the owning `INSTRUCTOR` for that course. |
| `404` | `item_id`/`question_id`/`option_id` doesn't exist, doesn't belong to an assessment of the expected type, or (for grading) the student hasn't submitted yet. |
| `422` | Standard FastAPI validation error (wrong types, out-of-range `pass_mark_percentage`, etc). |

---

## 9. End-to-end example: standing up a quiz from scratch

```http
POST /courses/{course_id}/sections/{section_id}/items
{ "title": "Module 1 Quiz", "item_type": "ASSESSMENT", "assessment_type": "QUIZ",
  "quiz_settings": { "max_attempts": 2, "pass_mark_percentage": 60 } }
→ 201, data.id = "item-1"

POST /courses/items/item-1/quiz/questions
{ "text": "2 + 2 = ?", "options": [
    { "text": "3", "is_correct": false }, { "text": "4", "is_correct": true } ] }
→ 201

POST /courses/items/item-1/quiz/questions
{ "text": "Pick all prime numbers", "allow_multiple_answers": true, "multi_answer_mode": "OR",
  "options": [
    { "text": "2", "is_correct": true }, { "text": "4", "is_correct": false },
    { "text": "5", "is_correct": true }, { "text": "9", "is_correct": false } ] }
→ 201

PATCH /courses/items/item-1/assessment
{ "due_date": "2026-09-01T23:59:00Z" }
→ 200
```

The quiz is now live for enrolled students on that course.
