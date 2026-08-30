# Course Content Enhancements — Instructor/Admin API Reference

This document covers four additions to course management:

1. **Document downloadability** — an instructor/admin can control whether a `DOCUMENT` curriculum item can be downloaded by students, or only viewed in-app.
2. **Certification eligibility toggle** — `certificate_enabled` is now part of the normal course create/update payload (previously only settable through the dedicated certificate-settings endpoint).
3. **Guest lecturers per section** — one or more guest instructors can be credited on a specific section, automatically added to the course's instructor list and flagged as guests.
4. **`LINKS` curriculum item type** — a new item type for pointing students at an external URL (article, tool, resource), alongside the existing `VIDEO`/`DOCUMENT`/`ASSESSMENT` types.

This is the companion doc to [`COURSE_CONTENT_ENHANCEMENTS_STUDENT_API.md`](./COURSE_CONTENT_ENHANCEMENTS_STUDENT_API.md), which covers how these show up on the student/learning side. Base URL prefix for everything below: `/courses`.

> ℹ️ Global response quirk: the API strips null/absent fields from JSON output. If a field isn't in the response, treat it as `null`/unset — don't treat its absence as an error.

---

## Conventions

- **Auth**: unless noted otherwise, every endpoint below requires `Authorization: Bearer <token>` for `ADMIN` or the course's owning `INSTRUCTOR` (`get_current_admin_or_instructor` + `ensure_can_manage`).
- **Response envelope**: `ApiResponse<T>` — `{ "success": true, "message": "...", "data": {...} }`.
- **Null stripping**: absent/null fields are stripped from JSON responses.

---

## User stories

- *As an instructor,* when I upload a course handout, I want students to only be able to read it inside the course player by default, and to explicitly flip a switch when I'm fine with them saving their own copy — so I don't accidentally give away material I want to keep platform-exclusive.
- *As an admin,* when I set up a course that gets new lessons added every month, I want certificates off by default so nobody gets a "completion" certificate for a course that's never really finished — and I want to be able to turn certificates on with the same form I use to edit everything else about the course, not a separate screen.
- *As an instructor,* when I bring in a guest speaker to cover one section of my course, I want to credit them by name on that section without creating them a full account, and I want them to automatically show up in the course's "Taught by" list so students can see who's teaching what.
- *As an instructor,* when I want to point students at a great external article or tool instead of hosting my own document or video for it, I want to add it as a first-class curriculum item — not just paste a URL into a text field somewhere.

---

## 1. Document downloadability

### Field

| Field | Type | Default | Notes |
|---|---|---|---|
| `downloadable` | bool | `false` | Only meaningful for `DOCUMENT` items. `false` = students can view/stream the document in the course player but can't fetch a fresh download link. `true` = the download endpoint works for everyone. |

### Setting it on creation

**`POST /courses/{course_id}/sections/{section_id}/items`**

```json
{
  "title": "Session Handout",
  "item_type": "DOCUMENT",
  "file_name": "handout.pdf",
  "downloadable": true
}
```

Omit `downloadable` (or send `false`) for the default view-only behavior. Ignored/no-op if sent on a `VIDEO`, `ASSESSMENT`, or `LINKS` item.

### Updating it

**`PATCH /courses/items/{item_id}`**

```json
{ "downloadable": true }
```

- Only valid on a `DOCUMENT` item — sending it on any other item type returns `400 Bad Request` ("This item is not a document").
- Standard partial-update semantics: omit the field entirely to leave it unchanged.

### Reading it back

Appears on the `document` object wherever it's returned — item-create response, `GET /courses/manage/{id}`, `GET /courses/{slug}`:

```json
{
  "document": {
    "file_name": "handout.pdf",
    "mime_type": "application/pdf",
    "file_size_bytes": 245000,
    "is_uploaded": true,
    "downloadable": true,
    "storage_key": "courses/.../handout.pdf"
  }
}
```

(`storage_key` only appears in the manage view, same as before this feature.)

### Enforcement

**`GET /courses/{slug}/items/{item_id}/download`** now checks `downloadable`:

- If `downloadable: true` — works exactly as before, for anyone with course access.
- If `downloadable: false` — only the course's admin or owning instructor gets a `200`; everyone else (including enrolled students) gets `403 Forbidden`: `"This document is not available for download"`.

This gate is specifically on the **download** endpoint. Students can still *view* the document inside the course player regardless of this flag — see the student doc for how `document_url` works on the learning endpoints. Think of `downloadable` as "can they save a copy," not "can they see it at all."

---

## 2. Certification eligibility toggle (`certificate_enabled`)

The underlying field isn't new — it already existed and already gates certificate issuance (see [`CERTIFICATES_INSTRUCTOR_ADMIN_API.md`](./CERTIFICATES_INSTRUCTOR_ADMIN_API.md)). What's new: it's now part of the **general course create/update payload**, and its **default flipped from `true` to `false`**.

| Field | Type | Default | Notes |
|---|---|---|---|
| `certificate_enabled` | bool | `false` | Whether completing this course can earn a certificate at all. |

### Why the default changed

A course that gets continuous content updates (no fixed "done" state) shouldn't hand a student a completion certificate for a moving target. New courses now start with certificates **off**; turn them on explicitly once the course is a fixed, completable body of content.

### Setting it

**`POST /courses`** / **`PATCH /courses/{id}`**

```json
{ "certificate_enabled": true }
```

Standard optional field on both — omit on create to default to `false`, omit on update to leave unchanged.

### Reading it

Now included on every course object (create/update/list/detail responses, public and manage):

```json
{
  "id": "b6e2a1f0-....",
  "title": "Intro to Trauma-Informed Care",
  "certificate_enabled": true,
  "...": "...other existing course fields..."
}
```

### Relationship to the dedicated certificate-settings endpoint

`PATCH /certificates/courses/{course_id}/settings` (documented in `CERTIFICATES_INSTRUCTOR_ADMIN_API.md`) still exists and still works — it's the only way to set `certificate_template_id`. Both endpoints write to the **same** `certificate_enabled` column, so whichever you touch last wins; there's no conflict, just two doors into the same setting. Use the general course form for the on/off toggle, and the certificate-settings endpoint only when you also need to assign a specific template.

---

## 3. Guest lecturers per section

### The model

- A section normally has no instructor concept of its own — the course's `instructors` list (owner + any co-instructors, from `POST /courses` / `PATCH /courses/{id}`) covers the whole course.
- Now, a section can additionally credit one or more **guest lecturers** by name. Each guest name you add:
  - Is automatically added to the course's `instructors` list (if not already there), flagged `is_guest: true`.
  - Is linked to that specific section, so the frontend can show "This section is taught by Dr. Guest Speaker" right where it's relevant.
- Guest instructors never need a platform account — they're name-only, same as an unlinked co-instructor, just explicitly flagged.

### Setting guest lecturers on a section

**`POST /courses/{course_id}/sections`** (create) or **`PATCH /courses/{course_id}/sections/{section_id}`** (update)

```json
{
  "title": "Module 3: Crisis Intervention",
  "order_index": 2,
  "guest_instructors": ["Dr. Amara Okafor", "Chidi Nwosu"]
}
```

| Field | Type | Notes |
|---|---|---|
| `guest_instructors` | `string[] \| null` | Names of guest lecturer(s) covering this section. Omit/`null` for a section taught by the course's regular instructor(s) — the default, unchanged behavior. |

- **On update, sending `guest_instructors` fully replaces the section's guest list** — it's not a merge/append, same convention as the course-level `instructors` field. Omit the field entirely on a `PATCH` to leave the existing guests untouched. Send `[]` to remove all guests from this section (their `CourseInstructor` credit on the course itself is **not** deleted — see below).
- Re-saving with the same name(s) is idempotent — it reuses the existing guest credit rather than creating a duplicate.
- ⚠️ **Renaming a guest is not "in place."** `guest_instructors` matches by name string, not by an id. If you change `"Dr. Amara Okafor"` to `"Dr. A. Okafor"` in the list, that creates a **new** guest-instructor credit under the new name; the old one stays credited on the course (now with no section linked to it) unless you also remove it everywhere it was used. If you need to genuinely rename a guest, treat it as: remove the old name from every section, then add the corrected name.

### Reading guest lecturers back

Every section object (from `GET /courses/manage/{id}`, `GET /courses/{slug}`, and the create/update section responses) now includes:

```json
{
  "id": "section-uuid",
  "course_id": "course-uuid",
  "title": "Module 3: Crisis Intervention",
  "order_index": 2,
  "items": [ "..." ],
  "guest_instructors": [
    {
      "user_id": null,
      "name": "Dr. Amara Okafor",
      "profile_picture_url": "https://ui-avatars.com/api/?name=D&background=6D28D9&color=ffffff&size=256&bold=true&length=1",
      "is_guest": true
    }
  ]
}
```

`guest_instructors` is `[]` for a section with no guests (the default/unchanged case).

`is_guest` is also now present on every entry in the **course-level** `instructors` array (`CourseInstructorReadDTO`) — `false` for a regular instructor, `true` for anyone credited as a guest. Use it to render a "Guest" badge next to their name wherever the course's full instructor list is shown.

> ⚠️ **Known gap:** the `POST .../sections` and `PATCH .../sections/{section_id}` **responses themselves** don't yet echo a resolved `guest_instructors` list — they return `[]` immediately after the call even if you just set guests. Re-fetch `GET /courses/manage/{course_id}` (or the public course detail) to see the resolved list with generated avatar URLs.

---

## 4. New `LINKS` curriculum item type

`CourseItemTypeEnum` now has a fourth value: `"LINKS"`, alongside the existing `"VIDEO"`, `"DOCUMENT"`, `"ASSESSMENT"`. Use it for pointing students at an external URL instead of hosting your own video/document for it.

### Creating a link item

**`POST /courses/{course_id}/sections/{section_id}/items`**

```json
{
  "title": "Further Reading",
  "item_type": "LINKS",
  "order_index": 3,
  "url": "https://example.org/articles/trauma-informed-practice",
  "label": "Trauma-Informed Practice: A Primer",
  "description": "A deeper dive into the concepts covered in this section, from the National Child Traumatic Stress Network."
}
```

| Field | Type | Notes |
|---|---|---|
| `url` | string (max 2000) | **Required** when `item_type = "LINKS"`. `400 Bad Request` ("url is required for link items") if omitted. |
| `label` | string \| null (max 255) | Optional display label for the link. Falls back to using the item's own `title` client-side if you don't set a separate label — both are available, use whichever fits your UI. |
| `description` | string \| null | Optional longer blurb about the resource. |

No upload flow, no credentials response — unlike `VIDEO`/`DOCUMENT`, a `LINKS` item is complete the instant you create it.

### Updating a link item

**`PATCH /courses/items/{item_id}`**

```json
{ "url": "https://example.org/updated-article", "label": "Updated Reading" }
```

Send any subset of `url`/`label`/`description`. Only valid on a `LINKS` item — sending them on any other item type returns `400 Bad Request` ("This item is not a link").

### Reading it back

```json
{
  "id": "item-uuid",
  "title": "Further Reading",
  "item_type": "LINKS",
  "order_index": 3,
  "is_preview": false,
  "link": {
    "url": "https://example.org/articles/trauma-informed-practice",
    "label": "Trauma-Informed Practice: A Primer",
    "description": "A deeper dive into the concepts covered in this section..."
  }
}
```

`link` is `null`/absent on every other item type, same pattern as `video`/`document`/`assessment`.

### Deleting a link item

**`DELETE /courses/items/{item_id}`** — works exactly as it does for any other item type. No storage cleanup happens (there's nothing uploaded), unlike deleting a `DOCUMENT` item.

---

## 5. Endpoint reference summary

All endpoints below already existed; this table lists only what's new/changed on each.

| Endpoint | What's new |
|---|---|
| `POST /courses` | Body accepts `certificate_enabled` (default `false`). |
| `PATCH /courses/{id}` | Body accepts `certificate_enabled` (optional, PATCH semantics). |
| `GET /courses`, `/featured`, `/recent`, `/enrolled`, `/bookmarked`, `/manage`, `/manage/{id}`, `/{slug}` | Every course object now includes `certificate_enabled`. Every `CourseInstructorReadDTO` (in `instructors`) now includes `is_guest`. |
| `POST /courses/{course_id}/sections` | Body accepts `guest_instructors: string[]`. |
| `PATCH /courses/{course_id}/sections/{section_id}` | Body accepts `guest_instructors: string[]` (replaces the full set). |
| `GET /courses/manage/{id}`, `GET /courses/{slug}` | Every section object now includes `guest_instructors: CourseInstructorReadDTO[]`. |
| `POST /courses/{course_id}/sections/{section_id}/items` | `item_type` accepts `"LINKS"`. Body accepts `downloadable` (DOCUMENT only) and `url`/`label`/`description` (LINKS only). |
| `PATCH /courses/items/{item_id}` | Body accepts `downloadable` (DOCUMENT only) and `url`/`label`/`description` (LINKS only). |
| `GET /courses/manage/{id}`, `GET /courses/{slug}`, item-create response | `document` object includes `downloadable`. Item objects include a new `link` object for `LINKS` items. |
| `GET /courses/{slug}/items/{item_id}/download` | Now returns `403` for non-privileged callers when the document's `downloadable` is `false`. |

---

## 6. Error responses you should handle

| Status | When |
|---|---|
| `400` | `url` missing when creating a `LINKS` item. `downloadable` sent in a `PATCH` for a non-document item. `url`/`label`/`description` sent in a `PATCH` for a non-link item. |
| `403` | Not the course's owner (and not admin) on any section/item management endpoint (unchanged, pre-existing rule). Non-privileged caller hitting the download endpoint for a non-downloadable document. |
| `404` | Course/section/item id doesn't exist (unchanged, pre-existing rule). |
| `422` | Standard FastAPI validation error (e.g. `url` over 2000 chars). |

---

## 7. Frontend implementation checklist

- [ ] Document item create/edit form: add a "Downloadable" toggle, off by default. Reflect `document.downloadable` when editing an existing document item.
- [ ] Course create/edit form: add a "Certificates enabled" toggle, off by default for new courses. Cross-check with the dedicated certificate-settings screen if you have one — both write the same field.
- [ ] Section create/edit form: add a repeatable "Guest lecturer" name field (simple text inputs, add/remove rows) that maps to `guest_instructors: string[]`. After saving, re-fetch the course/section detail to show the resolved list with avatars (don't rely on the create/update response for this).
- [ ] Wherever the course's full instructor list renders (`course.instructors`), show a "Guest" badge when `is_guest: true`.
- [ ] Wherever a section renders (curriculum builder, course detail), show its `guest_instructors` (if non-empty) as "This section is taught by ...".
- [ ] Add `"LINKS"` as a selectable item type in the curriculum builder, with its own form: `url` (required), `label` (optional), `description` (optional). No upload step — creation is a single API call.
- [ ] Curriculum item list rendering: handle `item.link` the same way you already handle `item.video`/`item.document`/`item.assessment` — pick the icon/renderer based on `item_type === "LINKS"`.
