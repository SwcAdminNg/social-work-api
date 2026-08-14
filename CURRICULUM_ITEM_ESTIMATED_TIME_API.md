# Curriculum Item — Estimated Completion Time

A new optional field, `estimated_minutes`, is now available on **every curriculum item**
(`VIDEO`, `DOCUMENT`, and `ASSESSMENT` — quiz or essay). It's a plain instructor-entered estimate
of how long a learner takes to get through the item (watch the video, read the document, take the
quiz, write the essay) — nothing computes or validates it against actual usage, it's just a display
hint.

Base URL prefix for everything below: `/courses`. Auth: `Authorization: Bearer <token>` for
`ADMIN` or the owning `INSTRUCTOR` (same as the rest of the item-management endpoints).

## Field

| Field | Type | Notes |
|---|---|---|
| `estimated_minutes` | int ≥ 0 \| null | Optional. `null`/omitted = no estimate set (existing behavior, fully backward compatible). |

## Setting it on creation

**`POST /courses/{course_id}/sections/{section_id}/items`**

Add `estimated_minutes` to the existing item-create payload — works identically for `VIDEO`,
`DOCUMENT`, and `ASSESSMENT` items:

```json
{
  "title": "Module 1 Quiz",
  "item_type": "ASSESSMENT",
  "assessment_type": "QUIZ",
  "estimated_minutes": 15,
  "quiz_settings": { "pass_mark_percentage": 40 }
}
```

```json
{
  "title": "Intro Video",
  "item_type": "VIDEO",
  "estimated_minutes": 8
}
```

Omit it (or send `null`) for no estimate.

## Updating it

**`PATCH /courses/items/{item_id}`**

Partial update, same endpoint used for `title`/`order_index`/`is_preview`:

```json
{ "estimated_minutes": 20 }
```

Send `"estimated_minutes": null` to clear an existing estimate. Omit the field entirely to leave
it unchanged.

## Reading it back

Appears on every item object returned by the API — `GET /courses/manage/{id}` (management tree),
`GET /courses/{slug}` (public course detail), and the item-create response — right alongside the
existing `title`/`order_index`/`is_preview` fields:

```json
{
  "id": "item-uuid",
  "title": "Module 1 Quiz",
  "item_type": "ASSESSMENT",
  "order_index": 3,
  "is_preview": false,
  "estimated_minutes": 15,
  "assessment": { "...": "..." }
}
```

`estimated_minutes` is stripped from the response entirely (not `estimated_minutes: null`) when
unset, per this API's standard null-stripping behavior.

## Also visible to students (read-only)

This lives on the item itself, so it automatically flows through to the student-facing
curriculum/item endpoints — no separate configuration needed, and no student-facing write path
(students never set or change it).

Base URL prefix for this part: `/learning`. Auth: any authenticated, enrolled user
(`Authorization: Bearer <token>`).

**`GET /learning/courses/{course_id}/curriculum`** — every item in the outline
(`LearningItemDTO`) includes it:
```json
{
  "id": "item-uuid",
  "title": "Module 1 Quiz",
  "item_type": "ASSESSMENT",
  "is_completed": true,
  "estimated_minutes": 15
}
```

**`GET /learning/courses/{course_id}/items/{item_id}`** — the full item-content response
(`LearningItemContentDTO`) includes it too, alongside whatever else that item type returns
(`video_url`, `document_url`, quiz questions, essay prompt, etc — see
[`ASSESSMENTS_STUDENT_API.md`](./ASSESSMENTS_STUDENT_API.md) for the assessment-specific fields):
```json
{
  "id": "item-uuid",
  "title": "Intro Video",
  "item_type": "VIDEO",
  "is_completed": false,
  "estimated_minutes": 8,
  "video_url": "https://..."
}
```

Same null-stripping rule applies: `estimated_minutes` is simply absent from the JSON (not `null`)
when the instructor hasn't set one for that item. Suggested UI treatment: show something like "~15
min" next to the item when present, and just omit the badge entirely when absent — don't render
"No estimate" or similar, since plenty of items legitimately won't have one set.
