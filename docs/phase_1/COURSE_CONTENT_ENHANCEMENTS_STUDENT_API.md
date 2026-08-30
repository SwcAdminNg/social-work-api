# Course Content Enhancements — Student API Reference

This document covers how four course-management additions show up on the **student-facing** side:
document downloadability, the certification eligibility toggle, guest lecturers per section, and a
new `LINKS` curriculum item type. It's the companion to
[`COURSE_CONTENT_ENHANCEMENTS_INSTRUCTOR_ADMIN_API.md`](./COURSE_CONTENT_ENHANCEMENTS_INSTRUCTOR_ADMIN_API.md),
which covers how instructors/admins configure all of this.

Nothing here requires a new integration from scratch — these are additive fields on endpoints your
frontend likely already calls (course browsing, course detail, the learning/curriculum endpoints).

> ℹ️ Global response quirk: the API strips null/absent fields from JSON output. If a field isn't in
> the response, treat it as `null`/unset — don't treat its absence as an error.

---

## Conventions

- **Auth**: course browsing/detail endpoints (`/courses/...`) work with optional auth, same as
  before. The learning endpoints (`/learning/...`) require `Authorization: Bearer <token>` for an
  enrolled user, same as before.
- **Response envelope**: `ApiResponse<T>` — `{ "success": true, "message": "...", "data": {...} }`.
- **Null stripping**: absent/null fields are stripped from JSON responses.

---

## User stories

- *As a student,* when I open a course handout, I want to read it right there in the app — but I
  should only see a "Download" button if the instructor actually allowed downloading it, so I don't
  get a broken/forbidden action in my UI.
- *As a student,* when I'm browsing courses, I want to know upfront whether finishing a course earns
  me a certificate, so I'm not surprised at the end.
- *As a student,* when I open a section that was taught by a guest speaker instead of my regular
  instructor, I want to see who that guest is right there in the section, so I know whose expertise
  I'm learning from.
- *As a student,* when a lesson points me to an external article or tool instead of an in-app video
  or document, I want that to show up as a normal part of the curriculum — with a title, a bit of
  context, and a link I can open — not feel like a broken or missing item.

---

## 1. Document downloadability

### What changed

A `DOCUMENT` curriculum item now carries a `downloadable` flag, set by the instructor/admin (default
`false` — off).

- **You can always view/stream a document you have access to**, regardless of `downloadable`. The
  URL you already use to render it in the course player (`document_url`, below) keeps working
  either way.
- **`downloadable` only controls whether you should be offered a "Download" action.** When it's
  `false`, don't render a download button/link at all — and if your UI happens to call the dedicated
  download endpoint anyway, it will return `403 Forbidden`.

### Where you'll see it

**`GET /learning/courses/{course_id}/items/{item_id}`** — the full item-content response now
includes `downloadable` for a `DOCUMENT` item:

```json
{
  "id": "item-uuid",
  "title": "Session Handout",
  "item_type": "DOCUMENT",
  "is_completed": false,
  "document_url": "https://....r2.dev/....pdf?X-Amz-Signature=...",
  "downloadable": true
}
```

- `document_url` — always populated when the document is uploaded, for in-app viewing (e.g. an
  embedded PDF viewer). Not affected by `downloadable`.
- `downloadable` — `true`/`false`. Only present for `DOCUMENT` items; absent for every other type.

### Actually downloading

**`GET /courses/{slug}/items/{item_id}/download`** — this is the endpoint to call from an explicit
"Download" button (as opposed to `document_url`, which is for inline viewing).

- Returns `{ "download_url": "..." }` normally.
- Returns **`403 Forbidden`** ("This document is not available for download") if the instructor has
  `downloadable` set to `false` for this document — **unless** you're the course's owning instructor
  or an admin, who can always download regardless of the flag.

**Recommended UI pattern:** use `document_url` from the learning endpoint to render the document
inline unconditionally; show a separate "Download" button only when `downloadable: true`, wired to
this endpoint.

---

## 2. Certification eligibility (`certificate_enabled`)

`certificate_enabled` is now visible on every course object you already fetch (course browsing,
course detail, enrolled courses):

```json
{
  "id": "b6e2a1f0-....",
  "title": "Intro to Trauma-Informed Care",
  "certificate_enabled": true,
  "...": "...other existing course fields..."
}
```

- `true` — completing this course can earn you a certificate (subject to the usual rules — see
  [`CERTIFICATES_STUDENT_API.md`](./CERTIFICATES_STUDENT_API.md) for exactly how/when it's issued).
- `false` — this course doesn't issue certificates at all (typically a course that's continuously
  updated rather than a fixed, finishable curriculum). Nothing else about the course changes —
  progress tracking, completion status, etc. all work the same; there's just no certificate at the
  end.

**Suggested UI treatment:** show a small "Certificate on completion" badge on the course card/detail
page when `certificate_enabled: true`, and simply omit it when `false` — don't render a "no
certificate" message, since most courses that don't issue one just won't mention it at all.

Nothing here requires calling the Certificates API differently — this field is purely informational,
so you can decide whether to show certificate-related messaging before the student even enrolls.

---

## 3. Guest lecturers per section

### What changed

A section can now be credited to one or more **guest lecturers** in addition to (or instead of) the
course's regular instructor(s).

### Where you'll see it

**Before enrolling — course browsing/detail (`GET /courses`, `GET /courses/{slug}`, etc.):** every
section object includes:

```json
{
  "id": "section-uuid",
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

**While taking the course — `GET /learning/courses/{course_id}/curriculum`:** each section in the
outline includes the same `guest_instructors` array:

```json
{
  "id": "section-uuid",
  "title": "Module 3: Crisis Intervention",
  "items": [ "..." ],
  "is_locked": false,
  "guest_instructors": [
    { "user_id": null, "name": "Dr. Amara Okafor", "profile_picture_url": "https://...", "is_guest": true }
  ]
}
```

`guest_instructors` is `[]` for the (default, common) case of a section taught by the course's
regular instructor(s) — no special handling needed, just render nothing extra when it's empty.

Also note: every entry in a course's top-level `instructors` array now carries `is_guest` too
(`false` for a regular instructor, `true` for a guest) — useful if you show the full "Taught by"
list somewhere and want to visually distinguish guests there as well.

**Suggested UI treatment:** on a section header, if `guest_instructors` is non-empty, show something
like "Guest lecturer: Dr. Amara Okafor" (or "Guest lecturers: A, B" for multiple) alongside or in
place of the course's main instructor byline for that section specifically.

---

## 4. New `LINKS` curriculum item type

Curriculum items can now have `item_type: "LINKS"`, alongside the existing `"VIDEO"`, `"DOCUMENT"`,
`"ASSESSMENT"`. Treat it as a fourth first-class item type in your curriculum renderer, not an edge
case.

### In the curriculum outline

**`GET /learning/courses/{course_id}/curriculum`** — a `LINKS` item appears like any other item:

```json
{
  "id": "item-uuid",
  "title": "Further Reading",
  "item_type": "LINKS",
  "is_completed": false,
  "estimated_minutes": 5
}
```

(Completion works the same way as any other item — see the existing item-completion endpoint;
nothing link-specific about it.)

### In the full item content

**`GET /learning/courses/{course_id}/items/{item_id}`** — for a `LINKS` item:

```json
{
  "id": "item-uuid",
  "title": "Further Reading",
  "item_type": "LINKS",
  "is_completed": false,
  "estimated_minutes": 5,
  "link_url": "https://example.org/articles/trauma-informed-practice",
  "link_label": "Trauma-Informed Practice: A Primer",
  "link_description": "A deeper dive into the concepts covered in this section, from the National Child Traumatic Stress Network."
}
```

| Field | Notes |
|---|---|
| `link_url` | The external URL. Open it in a new tab — don't try to embed/iframe arbitrary external sites. |
| `link_label` | Optional display label for the link (may differ from the item's own `title`). Falls back to using the item `title` if not set. |
| `link_description` | Optional longer blurb about the resource — show it as supporting copy above/below the link. |

### On the course detail / marketing view

**`GET /courses/{slug}`** — a `LINKS` item also appears in the curriculum tree there (subject to the
existing preview/enrollment gating that already applies to every item type):

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

Note the field name difference: the **course-detail** endpoint nests link fields under a `link`
object (matching how `video`/`document`/`assessment` are nested there), while the **learning**
item-content endpoint uses flat `link_url`/`link_label`/`link_description` fields (matching how
`video_url`/`document_url` are flat there). Same underlying data, two different response shapes
depending on which endpoint you're already consuming.

**Suggested UI treatment:** render a `LINKS` item with an external-link icon, its label/title, the
description underneath, and an "Open" action that opens `link_url` in a new tab. There's no "player"
to load — clicking through is the whole interaction, so consider marking it complete either
immediately or the moment the student clicks through, whichever matches how you handle completion
for similarly lightweight items today.

---

## 5. Endpoint reference summary

All endpoints below already existed; this table lists only what's new/changed on each.

| Endpoint | What's new |
|---|---|
| `GET /courses`, `/featured`, `/recent`, `/enrolled`, `/bookmarked`, `/{slug}` | Every course object includes `certificate_enabled`. Every instructor entry includes `is_guest`. Every section includes `guest_instructors`. A `LINKS` item includes a `link` object. |
| `GET /learning/courses/{course_id}/curriculum` | Every section includes `guest_instructors`. |
| `GET /learning/courses/{course_id}/items/{item_id}` | A `DOCUMENT` item includes `downloadable`. A `LINKS` item includes `link_url`/`link_label`/`link_description`. |
| `GET /courses/{slug}/items/{item_id}/download` | Now returns `403` when the document's `downloadable` is `false` (unless you're the course's instructor/admin). |

---

## 6. Error responses you should handle

| Status | When |
|---|---|
| `403` | Calling the document download endpoint for a document the instructor hasn't marked downloadable. Also unchanged pre-existing cases: not enrolled, section locked, scheduled course outside its access window. |
| `404` | Item/section/course id doesn't exist (unchanged, pre-existing rule). |

---

## 7. Frontend implementation checklist

- [ ] Document viewer: keep using `document_url` unconditionally for inline viewing. Only render a
  "Download" button when `downloadable === true`, pointed at
  `GET /courses/{slug}/items/{item_id}/download`. Handle a `403` from that endpoint gracefully
  (shouldn't normally happen if you're already checking `downloadable`, but don't crash if it does).
- [ ] Course card/detail: optionally show a "Certificate on completion" indicator when
  `certificate_enabled === true`; render nothing when `false`.
- [ ] Section header rendering: when `section.guest_instructors` is non-empty, show a "Guest
  lecturer(s)" byline for that section, separate from the course's main instructor credit.
- [ ] Curriculum renderer: add `"LINKS"` as a fourth item type alongside `VIDEO`/`DOCUMENT`/
  `ASSESSMENT` — icon, title, description, and an "Open" action that opens `link_url` (or
  `link.url` on the course-detail endpoint) in a new tab.
- [ ] Double-check any place you hardcode/switch on `item_type` values (e.g. an enum/union type in
  your frontend code) to make sure `"LINKS"` doesn't silently fall through to a default/unknown
  state.
