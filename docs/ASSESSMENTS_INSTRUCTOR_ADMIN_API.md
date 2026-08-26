# Assessments (Quiz, Essay & Quiz Group) — Instructor/Admin API Reference

This document covers the **generic Assessment system**: curriculum items that used to be a
single hard-coded `QUIZ` item type are now a generic `ASSESSMENT` item type with a pluggable
`assessment_type` (`QUIZ`, `ESSAY`, or `QUIZ_GROUP` today; more types can be added later without
another schema change). This doc is scoped to **instructor/admin (management) endpoints only** —
creating, configuring, and grading assessments. A separate doc covers the student-facing endpoints
(taking a quiz, submitting an essay, taking a quiz group).

`QUIZ_GROUP` is a **set of nested quizzes** ("sections"), each with its own question pool, taken
together in one sitting with a single overall score — see §5b.

Any assessment (QUIZ, ESSAY, or QUIZ_GROUP) can additionally be marked `is_final_assessment` to
gate the student's progress through the course's sections ("modules") — see §11.

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
  └── Assessment (assessment_type = QUIZ | ESSAY | QUIZ_GROUP, + optional due_date)
        ├── QUIZ       → CourseQuizSettings (max_attempts, pass_mark_percentage, show_result_to_student)
        │                + Questions (each with Options)
        ├── ESSAY      → CourseEssaySettings (question, description, submission_mode)
        └── QUIZ_GROUP → CourseQuizGroupSettings (max_attempts, pass_mark_percentage,
                          show_result_to_student, time_limit_seconds)
                          + Sections (the nested quizzes), each with its own pool of
                          Questions (each with Options) and a `questions_to_ask` count
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
| `item_type` | `"VIDEO" \| "DOCUMENT" \| "ASSESSMENT"` | yes | Use `"ASSESSMENT"` for quiz, essay, and quiz group. |
| `order_index` | int | no (default `0`) | |
| `is_preview` | bool | no (default `false`) | |
| `assessment_type` | `"QUIZ" \| "ESSAY" \| "QUIZ_GROUP"` | **required when `item_type = ASSESSMENT`** | 400 if missing. |
| `due_date` | ISO 8601 datetime \| null | no | Omit/`null` = no deadline. |
| `quiz_settings` | object \| null | no, only used when `assessment_type = QUIZ` | See below. Fully optional — all fields default. |
| `essay_settings` | object \| null | **required when `assessment_type = ESSAY`** | 400 if missing. |
| `quiz_group_settings` | object \| null | no, only used when `assessment_type = QUIZ_GROUP` | See §5b. Fully optional — all fields default. |
| `is_final_assessment` | bool | no (default `false`) | Marks this as the section's gating assessment — see §11. At most one per section (`400` otherwise). If `true` and the type's own `max_attempts` is left unset, it defaults to `1` instead of unlimited. |

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
| `pass_mark_percentage` | int, 0-100 | Default `70`. Only meaningfully enforced when this essay is a final assessment (§11) — a regular essay has nothing that "fails" it. |
| `max_attempts` | int ≥ 1 \| null | Default `null` (unlimited resubmission until graded, the historical behavior). For a *final* essay assessment, a **failed** grade (`score < pass_mark_percentage`) re-opens the submission for another attempt as long as this cap isn't reached yet — see §11.3. A **passing** grade always locks resubmission, same as before. |

`quiz_group_settings` (`CourseQuizGroupSettingsInDTO` — all optional):

| Field | Type | Default | Notes |
|---|---|---|---|
| `max_attempts` | int ≥ 1 \| null | `null` (unlimited) | |
| `pass_mark_percentage` | int, 0-100 | `70` | Applies to the **overall** score across every section combined, not per-section. |
| `show_result_to_student` | bool | `true` | Same visibility semantics as a standalone quiz. |
| `time_limit_seconds` | int ≥ 30 \| null | `null` (untimed) | Optional countdown timer. See §5b.4 for how the timer/auto-submit behaves. |

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

### Example — create a QUIZ_GROUP item

```http
POST /courses/{course_id}/sections/{section_id}/items
```
```json
{
  "title": "Module 1 Final (Nested Quizzes)",
  "item_type": "ASSESSMENT",
  "assessment_type": "QUIZ_GROUP",
  "quiz_group_settings": {
    "max_attempts": 2,
    "pass_mark_percentage": 60,
    "time_limit_seconds": 1800
  }
}
```
This only creates the empty shell (settings). Add sections (the nested quizzes) and their
questions afterward via §5b — same two-step pattern as a standalone quiz (create the item, then
add questions separately).

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

Partial update — only send the fields you want to change. This is a single endpoint for quiz,
essay, and quiz group; send `quiz_settings`, `essay_settings`, or `quiz_group_settings` matching
the item's actual `assessment_type` (sending the wrong one returns `400`).

### Request body — `CourseAssessmentUpdateDTO`

| Field | Type | Notes |
|---|---|---|
| `due_date` | ISO 8601 datetime \| null | Omit to leave unchanged. Send explicit `null` to **clear** an existing deadline. |
| `quiz_settings` | partial object \| null | Only valid if the item is a QUIZ. Any subset of `max_attempts`, `pass_mark_percentage`, `show_result_to_student`. |
| `essay_settings` | partial object \| null | Only valid if the item is an ESSAY. Any subset of `question`, `description`, `submission_mode`, `pass_mark_percentage`, `max_attempts`. |
| `quiz_group_settings` | partial object \| null | Only valid if the item is a QUIZ_GROUP. Any subset of `max_attempts`, `pass_mark_percentage`, `show_result_to_student`, `time_limit_seconds`. Send explicit `"time_limit_seconds": null` to turn an existing timer off. |
| `is_final_assessment` | bool \| null | Flip whether this assessment gates its section (§11). Omit to leave unchanged. Setting `true` when another assessment in the same section is already final returns `400`. |

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
  "is_final_assessment": true,
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
    "submission_mode": "TEXT",
    "pass_mark_percentage": 70,
    "max_attempts": null
  }
}
```

### Quiz group item shape (`assessment_type = "QUIZ_GROUP"`)

```json
{
  "id": "assessment-uuid",
  "assessment_type": "QUIZ_GROUP",
  "due_date": null,
  "quiz_group": {
    "max_attempts": 2,
    "pass_mark_percentage": 60,
    "show_result_to_student": true,
    "time_limit_seconds": 1800,
    "sections": [
      {
        "id": "section-uuid-1",
        "title": "Safety Principles",
        "order_index": 0,
        "questions_to_ask": 5,
        "questions": [ /* full CourseQuizQuestionManageDTO[] pool for this section, same shape as §5 */ ]
      },
      {
        "id": "section-uuid-2",
        "title": "De-escalation",
        "order_index": 1,
        "questions_to_ask": null,
        "questions": [ /* ... */ ]
      }
    ]
  }
}
```

- In the **manage** view, each section's full question pool is always shown (with `is_correct`),
  same as a standalone quiz — instructors need to see and edit everything.
- The **public/student-facing** view of a quiz group (used outside the dedicated take-the-quiz
  endpoints, e.g. course browsing) deliberately omits the pool entirely — each section only
  exposes `question_count` (how many questions will actually be asked). This is intentional: since
  questions are drawn at random per attempt (see §5b.3), showing the whole pool ahead of time would
  let a student study every possible question and defeat the point.
- `questions_to_ask: null` means "ask every question in the pool, every attempt" (no randomization
  for that section).

`quiz`, `essay`, and `quiz_group` are mutually exclusive — only the one matching `assessment_type`
is populated (the others are omitted, per the null-stripping rule).

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

## 5a. AI-generated quiz questions

There are two AI-powered authoring helpers for standalone `QUIZ` items:

- `ai-generate`: create questions from an instructor prompt, topics, or learning outcomes.
- `ai-autocomplete`: upload a PDF/DOCX and create questions from extracted document text.

Both return `generated_questions` in the same shape as the manual question-create endpoint
(`QuizQuestionCreateDTO`), and both optionally save the questions immediately. Saved questions
remain fully editable with the normal update/delete endpoints in §5.3-5.4.

Both endpoints support selectable AI providers:

| Provider value | Default model | Required env var |
|---|---|---|
| `GEMINI` | `gemini-3.7-flash` | `GEMINI_API_KEY` |
| `OPENAI` | `gpt-4o-mini` | `OPENAI_API_KEY` |
| `DEEPSEEK` | `deepseek-v4-flash` | `DEEPSEEK_API_KEY` |

You can also send a `model` override when the frontend wants to expose a provider's model picker.

### 5a.1 Generate from a prompt

**`POST /courses/items/{item_id}/quiz/ai-generate`**

Use this when the instructor wants to say something like "Create questions on child protection,
case notes, confidentiality, and ethical referrals". The user must be an admin or the owning
instructor. This endpoint does not support `ESSAY` or `QUIZ_GROUP` items yet.

Request body:

```json
{
  "prompt": "Create practical questions on confidentiality, mandated reporting, case documentation, and referral ethics for beginner social workers.",
  "question_count": 10,
  "options_per_question": 4,
  "persist": false,
  "provider": "OPENAI",
  "model": "gpt-4o-mini"
}
```

| Field | Type | Default | Notes |
|---|---|---|---|
| `prompt` | string, 1-5000 chars | required | Describe the topics, learning outcomes, difficulty, scenario style, or anything else the AI should follow. |
| `question_count` | int, 1-50 | `10` | The target number of generated questions. The AI provider may return fewer if the prompt is too narrow. |
| `options_per_question` | int, 2-6 | `4` | Every generated question gets this many options. |
| `persist` | bool | `true` | If `true`, generated questions are saved immediately. If `false`, the response is preview-only. |
| `provider` | `"GEMINI" \| "OPENAI" \| "DEEPSEEK"` | `"GEMINI"` | Which AI provider to call. |
| `model` | string \| null | provider default | Optional provider-specific model override. |

Response:

```json
{
  "success": true,
  "message": "Quiz generated successfully",
  "data": {
    "prompt": "Create practical questions on confidentiality, mandated reporting, case documentation, and referral ethics for beginner social workers.",
    "provider": "OPENAI",
    "model": "gpt-4o-mini",
    "persisted": false,
    "generated_questions": [
      {
        "text": "Which action best protects client confidentiality during case documentation?",
        "order_index": 0,
        "allow_multiple_answers": false,
        "options": [
          { "text": "Record only relevant professional information", "is_correct": true, "order_index": 0 },
          { "text": "Include informal opinions about the client", "is_correct": false, "order_index": 1 },
          { "text": "Share notes in a public messaging group", "is_correct": false, "order_index": 2 },
          { "text": "Avoid recording any risk concerns", "is_correct": false, "order_index": 3 }
        ]
      }
    ],
    "created_questions": []
  }
}
```

When `persist=true`, `created_questions` contains the saved question/option IDs.

### 5a.2 Autocomplete from PDF/DOCX

**`POST /courses/items/{item_id}/quiz/ai-autocomplete`**

Upload an existing assessment document and let the selected AI provider generate
quiz questions/options for an existing standalone `QUIZ` item. The user must be an admin or the
owning instructor. This endpoint does not support `ESSAY` or `QUIZ_GROUP` items yet.

Content type: `multipart/form-data`

| Field | Type | Default | Notes |
|---|---|---|---|
| `file` | PDF or DOCX file | required | Max size defaults to 10MB. Scanned PDFs must be OCR'd first. |
| `question_count` | int, 1-50 | `10` | The target number of generated questions. The AI provider may return fewer if the document is thin. |
| `options_per_question` | int, 2-6 | `4` | Every generated question gets this many options. |
| `persist` | bool | `true` | If `true`, generated questions are saved immediately. If `false`, the response is preview-only. |
| `provider` | `"GEMINI" \| "OPENAI" \| "DEEPSEEK"` | `"GEMINI"` | Which AI provider to call. |
| `model` | string \| null | provider default | Optional provider-specific model override. |

Example:

```http
POST /courses/items/{item_id}/quiz/ai-autocomplete
Content-Type: multipart/form-data
```

Response:

```json
{
  "success": true,
  "message": "Quiz generated successfully",
  "data": {
    "source_file_name": "module-1-assessment.pdf",
    "source_mime_type": "application/pdf",
    "extracted_text_preview": "Readable text extracted from the document...",
    "provider": "GEMINI",
    "model": "gemini-3.7-flash",
    "persisted": true,
    "generated_questions": [
      {
        "text": "Which action best reflects trauma-informed practice?",
        "order_index": 0,
        "allow_multiple_answers": false,
        "options": [
          { "text": "Prioritizing safety and consent", "is_correct": true, "order_index": 0 },
          { "text": "Pressuring the client to disclose", "is_correct": false, "order_index": 1 },
          { "text": "Ignoring cultural context", "is_correct": false, "order_index": 2 },
          { "text": "Making decisions without the client", "is_correct": false, "order_index": 3 }
        ]
      }
    ],
    "created_questions": [
      {
        "id": "question-uuid",
        "text": "Which action best reflects trauma-informed practice?",
        "order_index": 0,
        "allow_multiple_answers": false,
        "options": [
          { "id": "option-uuid", "text": "Prioritizing safety and consent", "order_index": 0, "is_correct": true }
        ]
      }
    ]
  }
}
```

Environment:

```dotenv
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-3.7-flash
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4o-mini
DEEPSEEK_API_KEY=your-deepseek-api-key
DEEPSEEK_MODEL=deepseek-v4-flash
```

Optional limits/config:

```dotenv
GEMINI_API_BASE_URL=https://generativelanguage.googleapis.com/v1beta
OPENAI_API_BASE_URL=https://api.openai.com/v1
DEEPSEEK_API_BASE_URL=https://api.deepseek.com
GEMINI_TIMEOUT_SECONDS=60
ASSESSMENT_AI_MAX_FILE_SIZE_BYTES=10485760
ASSESSMENT_AI_MAX_INPUT_CHARS=40000
```

Error responses to handle:

| Status | When |
|---|---|
| `400` | Unsupported file type, unreadable/corrupt document, empty document, or no extractable text. |
| `404` | `item_id` is not a standalone quiz item. |
| `413` | Uploaded file exceeds `ASSESSMENT_AI_MAX_FILE_SIZE_BYTES`. |
| `500` | The selected provider's API key is not configured. |
| `502` | The selected provider request failed, timed out, or returned invalid quiz JSON. |

---

## 5b. Quiz group sections (nested quizzes)

A `QUIZ_GROUP` assessment is a set of named **sections** — each one is its own mini quiz with its
own question pool. A student answers every section in one sitting and gets a single overall score.

### 5b.1 Add a section

**`POST /courses/items/{item_id}/quiz-group/sections`** — `item_id` is the course item's id, and
its `assessment_type` must already be `QUIZ_GROUP` (400 otherwise).

```json
{ "title": "Safety Principles", "order_index": 0, "questions_to_ask": 5 }
```

| Field | Type | Notes |
|---|---|---|
| `title` | string (1-255) | |
| `order_index` | int | default `0` |
| `questions_to_ask` | int ≥ 1 \| null | How many questions to randomly draw from this section's pool **per attempt**. `null`/omitted = ask every question in the pool, every time (no randomization). |

Response (`201`) — `CourseQuizGroupSectionManageDTO` (starts with an empty `questions: []`):
```json
{
  "success": true,
  "message": "Section created successfully",
  "data": { "id": "section-uuid", "title": "Safety Principles", "order_index": 0, "questions_to_ask": 5, "questions": [] }
}
```

### 5b.2 Update / delete a section

**`PATCH /courses/quiz-group/sections/{section_id}`** — partial update, any subset of `title`,
`order_index`, `questions_to_ask` (`QuizGroupSectionUpdateDTO`).

**`DELETE /courses/quiz-group/sections/{section_id}`** — soft-deletes the section. Its questions
are left in place (soft-delete doesn't cascade, matching how deleting a course section doesn't
cascade to its items either) but simply stop appearing anywhere once the parent section is gone.

### 5b.3 Add questions to a section's pool

**`POST /courses/quiz-group/sections/{section_id}/questions`** — same request/response shape as
the standalone-quiz question endpoint (§5.2, `QuizQuestionCreateDTO` → `CourseQuizQuestionManageDTO`),
just scoped to a section instead of directly to an item:

```json
{
  "text": "What is the first priority in a trauma-informed response?",
  "order_index": 0,
  "allow_multiple_answers": false,
  "options": [
    { "text": "Establishing safety", "is_correct": true, "order_index": 0 },
    { "text": "Documenting the incident", "is_correct": false, "order_index": 1 }
  ]
}
```

Add as many questions as you like to a section's pool — the more you add beyond `questions_to_ask`,
the more variety students see across retakes (see the "no repeats" behavior below).

**Updating/deleting individual questions and options** reuses the exact same endpoints as
standalone quizzes — `PATCH/DELETE /courses/quiz/questions/{question_id}`,
`POST /courses/quiz/questions/{question_id}/options`, `PATCH/DELETE /courses/quiz/options/{option_id}`
(§5.3-5.4). They resolve ownership via the question, regardless of whether it belongs to a
standalone quiz or a quiz-group section, so there's nothing quiz-group-specific to call there.
Grading semantics (single-answer, `AND`/`OR` multi-answer) are identical to §5.1 too.

### 5b.4 How "no repeated questions" and the timer work (so you can set pool sizes sensibly)

- Each attempt draws `questions_to_ask` questions per section **at random**, preferring questions
  the student hasn't been asked in any of their previous attempts on this item. Once every question
  in a section's pool has been shown at least once, it wraps around and starts reusing them (a pool
  can't produce more never-before-seen questions than it has). **Size your pools accordingly**: if
  `max_attempts: 3` and `questions_to_ask: 5`, a pool of 15+ guarantees no repeats across all 3
  attempts; a pool of 6 will start repeating on attempt 2.
- If `time_limit_seconds` is set on the group's settings, the student's attempt has a countdown
  from the moment they start it. If they don't submit in time, the **next time anything touches
  that attempt** (the student reopening the item, or their next start/progress/submit call) it is
  automatically finalized and scored using whatever answers were last saved via the student-side
  autosave endpoint (empty/unanswered for anything never saved). This shows up to you exactly like
  a normal submitted attempt, with no separate signal on your side — the student-facing result
  simply has `auto_submitted: true`.

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

### 7.1 Adding/removing items live-updates every enrolled student's completion

Relevant for courses that get built out gradually (e.g. a cohort where you add a new module
every week while students actively work through what already exists). Creating a new item
(any type), deleting an item, or deleting a whole section immediately recalculates
`progress_percent`/`is_completed` (`UserCourseProgress`) for **every currently enrolled
student**, not just whoever happens to interact with the course next:

- Add a new item to a course a student had already finished → that student's course flips
  back to **not completed** (their `progress_percent` drops below 100) until they also finish
  the new item. There is no "grandfathering" of an old completion — completion always reflects
  every currently-existing, non-deleted item in the course.
- Delete an item a student hadn't finished yet → their `progress_percent` recalculates against
  the smaller item count, and may become 100%/`is_completed: true` if that was the only thing
  left.
- This only touches the course-level `is_completed`/`progress_percent` rollup — per-item
  `UserItemProgress` rows for content the student already completed are untouched, and
  module-gating state (§11) is unaffected (it's derived independently, live, per request).
- This happens synchronously as part of the create/delete call - no extra step, nothing to
  poll. It touches every enrolled student in one transaction, so expect the call to take
  proportionally longer on a course with a large roster.

### 7.2 "New content" flag for students

Creating a new item also stamps `Course.content_updated_at = now()`. Every enrolled-course
listing exposes two fields per course, computed per-student against their own
`UserCourseProgress.last_accessed_at` (their last curriculum visit — falls back to enrollment
time if they've never opened it):

| Field | Type | Meaning |
|---|---|---|
| `content_updated_at` | datetime \| null | When a curriculum item was last added to this course. Null if nothing's ever been added since creation. |
| `has_new_content` | bool | `true` when `content_updated_at` is more recent than this student's last visit — i.e. there's material they haven't seen yet. Always `false` for a non-enrolled/anonymous viewer. |

Both appear on `GET /courses/enrolled`, `GET /courses` (and other course-listing endpoints that
call `attach_progress_status`), and the student-facing `GET /learning/courses`. `has_new_content`
clears itself automatically the next time the student opens `GET /learning/courses/{course_id}/curriculum`
— no separate "mark as seen" call needed. Deleting an item does **not** set `content_updated_at`
(only additions count as "new material").

---

## 8. Error responses you should handle

| Status | When |
|---|---|
| `400` | `item_type=ASSESSMENT` without `assessment_type`; `assessment_type=ESSAY` without `essay_settings`; `multi_answer_mode` set on a single-answer question; `quiz_settings`/`essay_settings`/`quiz_group_settings` sent for the wrong assessment type on the settings-patch endpoint. |
| `403` | Current user is neither `ADMIN` nor the owning `INSTRUCTOR` for that course. |
| `404` | `item_id`/`question_id`/`option_id`/`section_id` doesn't exist, doesn't belong to an assessment of the expected type, or (for grading) the student hasn't submitted yet. |
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

## 10. End-to-end example: standing up a quiz group from scratch

```http
POST /courses/{course_id}/sections/{section_id}/items
{ "title": "Module 1 Final", "item_type": "ASSESSMENT", "assessment_type": "QUIZ_GROUP",
  "quiz_group_settings": { "max_attempts": 2, "pass_mark_percentage": 60, "time_limit_seconds": 1800 } }
→ 201, data.id = "item-2"

POST /courses/items/item-2/quiz-group/sections
{ "title": "Safety Principles", "order_index": 0, "questions_to_ask": 2 }
→ 201, data.id = "section-1"

POST /courses/quiz-group/sections/section-1/questions
{ "text": "What is the first priority in a trauma-informed response?",
  "options": [ { "text": "Establishing safety", "is_correct": true },
               { "text": "Documenting the incident", "is_correct": false } ] }
→ 201
... (add more questions to section-1's pool)

POST /courses/items/item-2/quiz-group/sections
{ "title": "De-escalation", "order_index": 1, "questions_to_ask": 2 }
→ 201, data.id = "section-2"

POST /courses/quiz-group/sections/section-2/questions
{ ... }
→ 201
... (add more questions to section-2's pool)
```

The quiz group is now live — students see two sections, each drawing 2 random questions per
attempt, with a 30-minute timer and a single overall score across both sections.

---

## 11. Module gating and the redo-on-fail flow

Any assessment — QUIZ, ESSAY, or QUIZ_GROUP — can be marked `is_final_assessment: true` when you
create or patch it (§2/§3). Doing so turns its section into a **gate**:

- A student must **pass** that section's final assessment before the **next** section unlocks.
  Sections before the first locked one stay accessible; everything from the first locked section
  onward is locked too (no skipping ahead).
- A section with **no** final assessment configured just needs to be fully completed (every
  video/document/assessment item marked done) to unlock the next one — no pass/fail involved.
- The final assessment on the course's **last** section doubles as the course's final exam. Passing
  it completes the course. There's no separate "course final exam" concept to configure — whichever
  section is last (by `order_index`) automatically gets this behavior for its final assessment.

### 11.1 What happens when a student fails

Each final assessment has a retry cap — `max_attempts` (quiz/quiz-group) works exactly like §5.1,
and now essays have the same concept too (§6, `max_attempts` on `essay_settings`). **If you don't
set one, it defaults to `1`** the moment you mark something `is_final_assessment: true` — unlike a
regular assessment (which defaults to unlimited), a final assessment needs *some* cap or the reset
below can never trigger. Set it explicitly to whatever number of retries you want the student to
have before the reset kicks in.

When a student **exhausts their retries without passing**:

- If it's **not** the course's last section: **that section is reset** for the student — every
  video/document/assessment in it goes back to not-completed, and every attempt/submission history
  for its assessments is cleared (fresh attempt counters, essays re-open for a first submission).
  They redo the whole section from scratch, not just the final assessment.
- If it **is** the course's last section: the **entire course** is reset the same way, section by
  section, back to the very beginning.

Passing with retries to spare, or having a retry left after a fail, doesn't trigger anything — the
student just retries the final assessment itself, same as a normal quiz retry.

### 11.2 Where this shows up in the API

- The reset happens automatically as a side effect of the normal student-facing submit/grade calls
  (`quiz/submit`, `quiz-group/submit`, and your `essay/submissions/{user_id}/grade` call) — nothing
  extra to call on your side. A course-level reset triggered from grading an essay uses the same
  engine as a student's own quiz submission.
- `CourseSectionReadDTO`/`CourseSectionManageReadDTO` don't currently expose per-student lock state
  (that's a *per-student* concept, not a course-structure one) — see the student docs' curriculum
  endpoint for that.
- There's no instructor-facing "this student's progress was reset" notification beyond what you'd
  see by re-checking their submissions/attempts (they'll simply be gone) — the essay submissions
  list (§6.1) will stop showing a wiped submission, for example.

### 11.3 Essay-specific notes

Essays didn't have any pass/fail or retry concept before this — a regular (non-final) essay is
**unaffected**: unlimited resubmission until graded once, exactly as before. The new
`pass_mark_percentage`/`max_attempts` fields only do something once `is_final_assessment: true` is
set. When a final essay is graded with a **failing** score and retries remain, the student's
existing submission re-opens for a new attempt (their next `submit-text`/`submit-document` call
clears the old score/feedback back to "pending review" — you'll see it awaiting grading again, with
a fresh `submitted_at`). A **passing** grade, or a failing grade with no retries left, locks it
exactly like before (and the latter also triggers the reset described above).

### 11.4 Example: marking a module's quiz as the gate

```http
PATCH /courses/items/{quiz_item_id}/assessment
{ "is_final_assessment": true, "quiz_settings": { "max_attempts": 2, "pass_mark_percentage": 60 } }
→ 200
```
Students must now score ≥60% on this quiz, within 2 tries, before the next section unlocks for
them. A third failed attempt isn't possible (`400` at `max_attempts`) - the reset already fired
after the 2nd failure.
