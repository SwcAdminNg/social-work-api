# AI Assessment Authoring — Instructor API Reference

**Audience:** the instructor frontend (and the AI building it).

Instructors can have an AI model draft **multiple-choice quiz questions** for them, either from a **topic prompt** or from an **uploaded PDF/DOCX** (a past paper, lecture notes, a policy document). The questions are saved straight into the quiz, or returned for the instructor to review first.

Companion docs:
- [`INSTRUCTOR_COURSE_AUTHORING_AND_APPROVAL_API.md`](./INSTRUCTOR_COURSE_AUTHORING_AND_APPROVAL_API.md): course/quiz CRUD and the approval workflow (this doc plugs into §6.5–§6.6 there).
- [`../phase_1/ASSESSMENTS_INSTRUCTOR_ADMIN_API.md`](../phase_1/ASSESSMENTS_INSTRUCTOR_ADMIN_API.md): the original assessment reference.

---

## Contents

1. [Conventions and scope](#1-conventions-and-scope)
2. [User stories](#2-user-stories)
3. [How it works](#3-how-it-works)
4. [Endpoints](#4-endpoints)
5. [Request reference](#5-request-reference)
6. [Response reference](#6-response-reference)
7. [Recommended flows and screens](#7-recommended-flows-and-screens)
8. [Interaction with the approval workflow](#8-interaction-with-the-approval-workflow)
9. [Errors](#9-errors)
10. [Limits and operational notes](#10-limits-and-operational-notes)
11. [Implementation checklist](#11-implementation-checklist)

---

## 1. Conventions and scope

- Every call needs `Authorization: Bearer <token>` and edit permission on the course (the owning instructor, an admin, or someone with an editing role on it).
- Success responses use the envelope `{ "success": true, "message": "Quiz generated successfully", "data": {...} }`. Errors are `{ "success": false, "message": "…", "errors"?: [...] }`. Null fields are omitted.
- **What it can generate:** multiple-choice questions only (single-answer and multiple-answer).
- **Where it works:**
  - a standalone **`QUIZ`** item;
  - a **section of a `QUIZ_GROUP`** item (the question goes into that section's pool).
- **What it can't do:** `ESSAY` assessments (there are no questions to generate), and it doesn't create the quiz item itself. Create the item first (the course doc §6.2).
- **Providers:** `GEMINI` (default), `OPENAI`, `DEEPSEEK`.

---

## 2. User stories

1. *As an instructor*, I describe the topic and difficulty ("10 questions on recognising neglect, scenario-based, for beginners") and get a ready-made quiz I can edit.
2. *As an instructor*, I upload my existing assessment or lecture notes (PDF or Word) and get questions built from that document.
3. *As an instructor*, I can **preview** the generated questions before anything is saved, keep the good ones, edit the rest and discard the others.
4. *As an instructor*, I can choose how many questions to generate and how many answer options each has.
5. *As an instructor*, I can choose which AI provider (and optionally which model) to use, in case one is slow or unavailable.
6. *As an instructor*, I can fill a quiz group section's question pool the same way, section by section.
7. *As an instructor*, I stay in control: every AI question can be edited, reordered or deleted like one I wrote myself, and it still goes through the normal course review before learners see it.

---

## 3. How it works

```
 Instructor ──► prompt  OR  PDF/DOCX ──► API ──► AI provider (Gemini / OpenAI / DeepSeek)
                                          │
                                          ├─ validates the AI output (option count, at least one correct answer)
                                          ├─ persist = false → returns questions only (nothing saved)
                                          └─ persist = true  → saves them into the quiz and returns them with ids
```

Rules applied to every generated question (server-side, so the frontend can rely on them):
- Each question has **exactly** `options_per_question` options. A question with fewer is rejected and the whole request fails (`502`).
- Each question has **at least one** correct option. A question with none fails the request (`502`).
- If exactly one option is correct → `allow_multiple_answers: false`, `multi_answer_mode` absent.
- If more than one option is correct → `allow_multiple_answers: true`, `multi_answer_mode: "OR"` (partial credit per correct tick).
- Extra questions or options beyond what was asked are dropped. The AI **may return fewer questions than requested** if the prompt or document is thin.
- `order_index` is renumbered `0…n-1` **within this batch** (see the ordering note in §10).
- The AI is told to avoid trivia, to stay within the source (document mode: no invented facts), and to write clearly for social work learners. The prompt also includes the course, module and item titles for context.

---

## 4. Endpoints

| Target | Mode | Method and path |
|---|---|---|
| Standalone quiz | From a prompt | `POST /courses/items/{item_id}/quiz/ai-generate` |
| Standalone quiz | From a document | `POST /courses/items/{item_id}/quiz/ai-autocomplete` |
| Quiz-group section | From a prompt | `POST /courses/quiz-group/sections/{section_id}/ai-generate` |
| Quiz-group section | From a document | `POST /courses/quiz-group/sections/{section_id}/ai-autocomplete` |

- `{item_id}` is the id of the `ASSESSMENT` course item whose `assessment_type` is `QUIZ`. Using a non-quiz item returns `404 "Quiz not found for this item"`.
- `{section_id}` is the id of a quiz-group section (from `POST /courses/items/{item_id}/quiz-group/sections` or the manage tree). A section that isn't part of a quiz group returns `404`.
- The `ai-generate` calls are JSON. The `ai-autocomplete` calls are `multipart/form-data`.

---

## 5. Request reference

### 5.1 From a prompt — `ai-generate` (JSON)

```json
POST /courses/items/{item_id}/quiz/ai-generate
{
  "prompt": "Scenario-based questions on recognising signs of neglect in children under five. Beginner level. Include one question with more than one correct answer.",
  "question_count": 10,
  "options_per_question": 4,
  "persist": false,
  "provider": "GEMINI",
  "model": null
}
```

| Field | Type | Default | Notes |
|---|---|---|---|
| `prompt` | string, 1–5000 chars | **required** | Topics, learning outcomes, difficulty, style (scenarios, definitions), anything the AI should follow. Where it's broad, the AI uses standard social work education knowledge. |
| `question_count` | int, 1–50 | `10` | A target; fewer may come back |
| `options_per_question` | int, 2–6 | `4` | Exact number of options on every question |
| `persist` | bool | `true` | `true` saves the questions into the quiz; `false` just returns them |
| `provider` | `GEMINI` \| `OPENAI` \| `DEEPSEEK` | `GEMINI` | |
| `model` | string, 1–100 chars, optional | server default | Override the provider's model. Leave it out unless an admin tells you a specific one. |

Server default models: Gemini `gemini-3.7-flash`, OpenAI `gpt-4o-mini`, DeepSeek `deepseek-v4-flash`. The model actually used is echoed back in the response.

### 5.2 From a document — `ai-autocomplete` (multipart)

```
POST /courses/items/{item_id}/quiz/ai-autocomplete
Content-Type: multipart/form-data

file=@past-paper.pdf
question_count=10
options_per_question=4
persist=false
provider=OPENAI
model=
```

| Form field | Type | Default | Notes |
|---|---|---|---|
| `file` | file, **required** | | `.pdf` or `.docx` only. At most **10 MB**. |
| `question_count` | int, 1–50 | `10` | |
| `options_per_question` | int, 2–6 | `4` | |
| `persist` | bool | `true` | Send the literal strings `true` / `false` |
| `provider` | `GEMINI` \| `OPENAI` \| `DEEPSEEK` | `GEMINI` | |
| `model` | string, optional | server default | Omit the field rather than sending an empty string |

How the document is handled:
- File type is detected from the extension (`.pdf` / `.docx`) or the content type.
- Text is extracted (PDF text layer; DOCX paragraphs **and tables**). The text is normalised and **truncated to the first 40,000 characters**; anything beyond is ignored.
- **Scanned/image-only PDFs have no text layer** and fail with `400` ("Scanned PDFs need OCR before upload").
- The document should contain the material to build questions from (notes, a policy, an existing paper). It does **not** need to already be in question format.

---

## 6. Response reference

### 6.1 `ai-generate` response

```json
{
  "success": true,
  "message": "Quiz generated successfully",
  "data": {
    "prompt": "Scenario-based questions on recognising signs of neglect…",
    "provider": "GEMINI",
    "model": "gemini-3.7-flash",
    "persisted": false,
    "generated_questions": [
      {
        "text": "A health visitor notices a 3-year-old is consistently unwashed and hungry. What is the most appropriate first step?",
        "order_index": 0,
        "allow_multiple_answers": false,
        "options": [
          { "text": "Record concerns and follow the safeguarding referral procedure", "is_correct": true, "order_index": 0 },
          { "text": "Wait to see if things improve", "is_correct": false, "order_index": 1 },
          { "text": "Confront the parents in front of the child", "is_correct": false, "order_index": 2 },
          { "text": "Ignore it unless there is physical injury", "is_correct": false, "order_index": 3 }
        ]
      },
      {
        "text": "Which of these are recognised indicators of neglect?",
        "order_index": 1,
        "allow_multiple_answers": true,
        "multi_answer_mode": "OR",
        "options": [
          { "text": "Persistent hunger", "is_correct": true, "order_index": 0 },
          { "text": "Inappropriate clothing for the weather", "is_correct": true, "order_index": 1 },
          { "text": "Enjoys sport", "is_correct": false, "order_index": 2 },
          { "text": "Has a new haircut", "is_correct": false, "order_index": 3 }
        ]
      }
    ],
    "created_questions": []
  }
}
```

### 6.2 `ai-autocomplete` response

Same as above, but with the source details instead of `prompt`:

```json
{
  "data": {
    "source_file_name": "past-paper.pdf",
    "source_mime_type": "application/pdf",
    "extracted_text_preview": "First 1000 characters of the extracted text…",
    "provider": "OPENAI",
    "model": "gpt-4o-mini",
    "persisted": true,
    "generated_questions": [ /* same shape as 6.1 */ ],
    "created_questions": [ /* saved questions, with ids, when persisted */ ]
  }
}
```

Show `extracted_text_preview` so the instructor can confirm the right file was read (and spot garbled extraction).

### 6.3 Field notes

| Field | Meaning |
|---|---|
| `persisted` | Echo of the `persist` you sent |
| `generated_questions` | **Always present.** Questions in the **create-question payload shape** (no ids). Sending one of these as-is to `POST /courses/items/{item_id}/quiz/questions` creates it. |
| `created_questions` | **Only when `persisted` is `true`.** The saved questions in editor format, with ids and `is_correct` on every option: `{ id, text, order_index, allow_multiple_answers, multi_answer_mode?, options: [{ id, text, order_index, is_correct }] }`. It's `[]` when `persist` is `false`. |
| `model` | The model that actually answered |

---

## 7. Recommended flows and screens

### 7.1 Flow A — Review before saving (recommended default)

1. On the quiz editor, the instructor clicks **Generate with AI** and picks **From a topic** or **From a document**.
2. The form collects: prompt (or file), number of questions, options per question, provider (advanced).
3. Call with **`persist: false`**. Show a loading state (see §10: it can take up to a minute).
4. Render `generated_questions` as editable cards (question text, options, a correct-answer marker, a delete control and a checkbox).
5. When the instructor clicks **Add selected**, save each kept question with the normal create call, in order:
   `POST /courses/items/{item_id}/quiz/questions` (or `…/quiz-group/sections/{section_id}/questions`) with the (possibly edited) question body.
6. Re-fetch the manage tree (`GET /courses/manage/{course_id}`) and show the saved questions.

Giving each saved question an `order_index` after the existing ones keeps the order sensible (see §10).

### 7.2 Flow B — Save immediately

1. Same form, but call with **`persist: true`**.
2. The response's `created_questions` are already in the quiz. Show them in the editor for tweaking (edit via `PATCH /courses/quiz/questions/{id}` and `PATCH /courses/quiz/options/{id}`, delete via `DELETE`).
3. Offer **Undo** by deleting the returned ids (`DELETE /courses/quiz/questions/{question_id}`), because the API has no batch-undo.

Use Flow B only when the instructor opted for **Generate and add**. Every click adds a full new batch, so disable the button while a request is running.

### 7.3 Quiz-group sections

Same flows, targeted at a section. Add a **Generate with AI** control inside each section's question pool. Remember `questions_to_ask` on the section (how many of the pool are drawn per attempt) should be ≤ the number of questions in the pool; suggest generating more questions than `questions_to_ask`.

### 7.4 Suggested form

| Control | Maps to |
|---|---|
| Tabs: *From a topic* / *From a document* | `ai-generate` / `ai-autocomplete` |
| Textarea (max 5000, with counter) | `prompt` |
| File drop (PDF/DOCX, 10 MB) | `file` |
| Stepper 1–50 (default 10) | `question_count` |
| Stepper 2–6 (default 4) | `options_per_question` |
| Toggle "Review before adding" (default on) | `persist` = `false` |
| Advanced: provider select, model | `provider`, `model` |

Prompt tips to show as placeholder text: audience level, scenario vs definition style, topic list, "include one multi-answer question".

---

## 8. Interaction with the approval workflow

AI questions are ordinary quiz questions once saved, so all of the course approval rules apply (see the course doc, §3 and §7). Key consequences:

- **Under review = locked.** If the course's revision is under review (or the course is archived), the AI endpoints return `409` **even with `persist: false`**. Withdraw the revision (or wait for it to be returned) first. Gate the **Generate with AI** button on the revision being editable (`is_editable`, or `available_actions` containing `EDIT`).
- **Generating opens the working copy.** On a published course, the first call (even a preview) opens the hidden working copy and records the caller as a contributor, as any edit would. The caller then cannot approve that revision later.
- **Risk:** adding questions to an existing assessment is a **HIGH-risk** change (and pulls in the Assessment Moderator stage). Warn the instructor on a published course: "Adding questions sends this course through full review."
- **Ids:** on a published course, saved question ids belong to the working copy. Re-fetch the manage tree rather than relying on returned ids across other edits.
- **Learners:** nothing appears to learners until the revision is published (or, for a never-published course, the course is published).
- The AI is a drafting aid. The reviewers still check answers, and the correct answers are visible to them in the revision's editor-format tree.

---

## 9. Errors

| Status | Message (example) | Cause | UI behaviour |
|---|---|---|---|
| `400` | "Uploaded assessment document is empty" | Zero-byte file | Ask for another file |
| `400` | "Only PDF and DOCX assessment documents are supported" | Wrong file type | Restrict the file picker; show the message |
| `400` | "No readable text was found in the document. Scanned PDFs need OCR before upload." | Image-only PDF | Suggest a text-based PDF or a DOCX |
| `400` | "Could not read the PDF/DOCX assessment document" | Corrupt or protected file | Ask for another file |
| `400` | "multi_answer_mode can only be set when allow_multiple_answers is true" | Only if you later save a hand-edited question wrongly | Fix the question body |
| `403` | "You do not manage this course" / missing permission | Not allowed to edit the course | Hide the feature |
| `404` | "Quiz not found for this item" / "Section not found" / "Quiz group not found for this section" | Wrong item type or id | Check the id and the item's `assessment_type` |
| `409` | "This course's changes are under review (…) and can't be edited. Withdraw the revision…" | Revision locked | Show the read-only banner |
| `409` | "This course is archived - reinstate it before editing" | Archived | Disable |
| `413` | "Assessment document must be 10MB or smaller" | File too large | Validate size on the client first |
| `422` | Validation error (for example `prompt` empty, `question_count` out of 1–50, `options_per_question` out of 2–6) | Bad input | Show field errors |
| `500` | "GEMINI_API_KEY is not configured" (or `OPENAI_`/`DEEPSEEK_`) | That provider isn't set up on the server | Offer another provider; tell the user to contact an admin |
| `502` | "Gemini/OpenAI/DeepSeek could not generate quiz questions: …" | The provider rejected or failed the call | Offer **Retry** or a different provider |
| `502` | "… request failed" | Network/timeout reaching the provider | Offer **Retry** |
| `502` | "AI provider returned invalid JSON" / "…quiz data in an unexpected shape" / "…did not generate any quiz questions" | Bad AI output | Offer **Retry** (a retry often succeeds) |
| `502` | "AI provider generated a question with fewer than N options" / "…with no correct answer" | AI output failed validation | Offer **Retry**; a different provider or a more specific prompt helps |

On any `502`, **nothing is saved**, so retrying is safe. Validation of the whole batch happens before any question is written.

---

## 10. Limits and operational notes

- **Latency:** the provider call has a **60-second** timeout on the server. Use a client timeout of at least **90 seconds**, show a progress state, and disable the submit button while waiting.
- **Not idempotent when `persist: true`.** A retry after a *timeout on the client* may have already saved a batch. Before retrying, refresh the quiz and check for new questions.
- **Ordering:** each batch is numbered `order_index: 0…n-1`, regardless of how many questions the quiz already has. After adding, either set sensible `order_index` values yourself when saving (Flow A: use `existing_count + i`) or fix ordering with `PATCH /courses/quiz/questions/{id}` `{ "order_index": … }`. The manage tree returns questions with their `order_index`.
- **Document size:** files up to 10 MB; only the first 40,000 characters of text are used. Tell instructors to split very long documents or to upload the relevant chapter.
- **Question count:** the AI may return fewer than `question_count`, never more.
- **Provider availability:** there is no endpoint that lists configured providers. If one returns `500 … is not configured`, fall back to another. Keep `GEMINI` as the default.
- **Cost:** each call is one paid provider request. Disable the button while running, and don't auto-retry silently.
- **Content quality:** answers are AI-drafted. Surface a short notice: *"AI-generated. Check every question and the marked correct answers before submitting for review."*
- **Privacy:** uploaded documents are read in memory, their text is sent to the chosen provider, and the file itself is not stored.
- **Server configuration** (for admins; not exposed in the API): `GEMINI_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`; optional `*_MODEL` and `*_API_BASE_URL`; `GEMINI_TIMEOUT_SECONDS` (60); `ASSESSMENT_AI_MAX_FILE_SIZE_BYTES` (10 MB); `ASSESSMENT_AI_MAX_INPUT_CHARS` (40,000).

---

## 11. Implementation checklist

- [ ] **Generate with AI** entry point on every quiz editor and every quiz-group section, enabled only when the revision is editable (§8).
- [ ] Two modes: topic (JSON) and document (multipart, PDF/DOCX, ≤ 10 MB validated client-side).
- [ ] Controls for question count (1–50), options per question (2–6), "Review before adding", and an advanced provider/model selector.
- [ ] Flow A: preview cards with edit, delete and select, then save through the normal create-question endpoint (§7.1).
- [ ] Flow B: persisted results shown immediately, with edit, delete and an undo that deletes by returned ids (§7.2).
- [ ] Show `extracted_text_preview` for document mode.
- [ ] Long-running state with a ≥ 90-second client timeout, a disabled submit button, and a cancel/return option.
- [ ] Retry affordance for `502`, a provider switch for `500`/`502`, and a locked-state message for `409`.
- [ ] After any save, re-fetch `GET /courses/manage/{course_id}`; fix `order_index` after batches (§10).
- [ ] "AI-generated, please review" notice, and a warning that adding questions to a published course triggers full review (§8).
