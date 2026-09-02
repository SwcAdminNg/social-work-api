# Certificates — Instructor/Admin API Reference

This document covers the **management** side of the certificate system: designing certificate
templates and assigning one to a course. A separate doc covers the student-facing side (viewing/
downloading an earned certificate, public verification) —
[`CERTIFICATES_STUDENT_API.md`](./CERTIFICATES_STUDENT_API.md).

A certificate is issued **automatically** the moment a student completes a course
(`UserCourseProgress.is_completed` flips to `true`) — there is no "issue certificate" endpoint to
call yourself. Your job as admin/instructor is entirely about the **design**: create one or more
templates, then point a course at the one you want (or leave it unset and it falls back to a global
default).

Base URL prefix for everything below: `/certificates`, except course assignment which lives under
`/certificates/courses/{course_id}/settings`.

## Conventions

- **Auth**: every endpoint below requires `Authorization: Bearer <token>` for a user who is either
  `ADMIN` or `INSTRUCTOR` (`get_current_admin_or_instructor`). Template endpoints additionally check
  **ownership** — see §1. The course-settings endpoint requires the caller to own the course (or be
  admin), same rule as every other course-management endpoint.
- **Response envelope**: `ApiResponse<T>` — `{ "success": true, "message": "...", "data": {...} }`.
  `GET /certificates/templates` (list) returns `PaginatedResponse<T>` with a `meta` block.
- **Null stripping**: absent/null fields are stripped from JSON responses — treat a missing field as
  `null`.
- **Colors**: `primary_color`, `accent_color`, `background_color`, `text_color` are 7-character hex
  strings, e.g. `"#0B3D2E"`.

---

## 1. The mental model

```
CertificateTemplate (owner_id = null → "global", visible to every instructor as a ready-made option
                      owner_id = instructor's id → private to that instructor)
        │
        │ assigned via Course.certificate_template_id
        ▼
Course ──── certificate_enabled (bool, default true)
        │
        │ the moment a student's course progress hits 100%...
        │ (for a SCHEDULED course, only once access_end_date has also passed — see §1.1)
        ▼
Certificate (one per student per course, issued automatically)
  - certificate_number, verification_code
  - student_profile_picture_url (snapshotted at issuance and shown on the PDF)
  - pdf_url (rendered lazily on first view/download — see student doc)
```

- **Global vs. private templates**: an `ADMIN` who creates a template makes it **global**
  (`owner_id: null`) — every instructor can see it in their list and assign it to their own
  courses, but can't edit or delete it. An `INSTRUCTOR` who creates a template owns it privately —
  only they (and admins) can see, edit, assign, or delete it.
- **Resolving which template a course actually uses**: if `Course.certificate_template_id` is set
  (and that template is still `is_active`), that's the one used. If it's unset, or the assigned
  template was deactivated, the system falls back to the **oldest active global template** — so a
  course "just works" the moment at least one global template exists, with zero configuration
  needed. If there is no global template *and* the course has none assigned, no certificate is
  issued (silently — course completion itself is unaffected either way).
- **Student profile picture is required**: no new certificate is issued unless the student has a
  profile picture URL on their account. If they completed the course first, they can upload a
  profile picture and request their certificate again; issuance will be attempted then.
- **You never render a PDF yourself.** Templates are pure configuration (colors, copy, images).
  Rendering happens lazily server-side the first time a student (or the public verify page) actually
  requests the certificate — see the student doc.

### 1.1 SCHEDULED courses: certificates wait for the course's deadline, not the student's

A course's `access_mode` (set via the regular course-management endpoints, not this API) can be
`SELF_PACED` or `SCHEDULED`. A `SCHEDULED` course carries `access_start_date`/`access_end_date` — a
defined "term" for the whole cohort.

- **`SELF_PACED` course** (or a `SCHEDULED` course with no `access_end_date` set): unchanged —
  the certificate is issued the instant the student finishes.
- **`SCHEDULED` course with `access_end_date` set**: even if a student finishes every item well
  before that date, **no certificate is issued yet**. It's held back until `access_end_date`
  actually passes — mirroring a cohort where everyone is certified together at the course's
  official end, not the moment each person personally finishes. Nothing is lost or needs
  re-triggering on your side: a daily background sweep
  (`POST /certificates/cron/process-scheduled-certificates`, QStash-triggered, not something you
  call directly — same pattern as the subscription-renewal cron) finds every student who already
  completed such a course and issues the backlog the day its deadline passes.
- This check is re-evaluated fresh every time issuance is attempted, so pushing
  `access_end_date` further out (via the course-management API) after a student has already
  finished will correctly keep withholding their certificate until the new date passes; pulling it
  earlier (into the past) makes it eligible on the very next sweep.
- `certificate_enabled: false` (§3) still wins over everything above — a disabled course never
  issues certificates regardless of schedule.

---

## 2. Certificate templates

### 2.1 Create a template

**`POST /certificates/templates`**

### Request body — `CertificateTemplateCreateDTO`

| Field | Type | Default | Notes |
|---|---|---|---|
| `name` | string (max 150) | — | **required**. Your own label for picking it later, e.g. `"Gold Seal — Advanced Courses"`. |
| `title_text` | string (max 150) | `"Certificate of Completion"` | The big headline on the certificate. |
| `subtitle_text` | string \| null (max 255) | `"This certificate is proudly presented to"` | Sits above the recipient's name. |
| `body_text` | string | see below | The paragraph under the recipient's name. Supports placeholders — see §2.2. |
| `organization_name` | string (max 150) | `"Social Work Nigeria Academy"` | Shown near the logo. |
| `footer_text` | string \| null (max 255) | `null` | Small print at the very bottom (e.g. a disclaimer or tagline). |
| `signature_name` | string \| null (max 150) | `null` | Name under the signature line. |
| `signature_title` | string \| null (max 150) | `null` | Title/role under the signature name (e.g. `"Program Director"`). |
| `primary_color` | hex string | `"#0B3D2E"` | Main frame/title color. |
| `accent_color` | hex string | `"#D4AF37"` | Highlight color (title text, inner border line). |
| `background_color` | hex string | `"#FFFDF7"` | Page background. |
| `text_color` | hex string | `"#1F2937"` | Body copy color. |
| `font_family` | string (max 50) | `"Helvetica"` | One of `Helvetica`, `Times-Roman`, `Courier` (bold variants are picked automatically for headings — any other value silently falls back to `Helvetica`). |
| `border_style` | `"CLASSIC" \| "MODERN" \| "NONE"` | `"CLASSIC"` | See §2.3. |

The default `body_text` is:
```
for successfully completing the course "{course_title}" on {completion_date}, demonstrating
dedication and mastery of the material.
```

Logo and signature images are **not** set on create — upload them afterward (§2.4), since they
need the template's `id` for the storage key.

### Example

```http
POST /certificates/templates
```
```json
{
  "name": "Classic Achievement",
  "title_text": "Certificate of Completion",
  "subtitle_text": "This certificate is proudly presented to",
  "body_text": "for successfully completing \"{course_title}\" on {completion_date}, having met all requirements with distinction.",
  "organization_name": "Social Work Nigeria Academy",
  "signature_name": "Dr. Amara Okafor",
  "signature_title": "Program Director, Social Work Nigeria Academy",
  "primary_color": "#0B3D2E",
  "accent_color": "#D4AF37",
  "background_color": "#FFFDF7",
  "border_style": "CLASSIC"
}
```

### Response — `201 Created`

```json
{
  "success": true,
  "message": "Certificate template created successfully",
  "data": {
    "id": "8e47937e-....",
    "owner_id": "instructor-uuid",
    "name": "Classic Achievement",
    "title_text": "Certificate of Completion",
    "subtitle_text": "This certificate is proudly presented to",
    "body_text": "for successfully completing \"{course_title}\" ...",
    "organization_name": "Social Work Nigeria Academy",
    "signature_name": "Dr. Amara Okafor",
    "signature_title": "Program Director, Social Work Nigeria Academy",
    "primary_color": "#0B3D2E",
    "accent_color": "#D4AF37",
    "background_color": "#FFFDF7",
    "text_color": "#1F2937",
    "font_family": "Helvetica",
    "border_style": "CLASSIC",
    "is_active": true,
    "is_global": false,
    "created_at": "2026-08-23T10:00:00Z"
  }
}
```

`owner_id` is `null` and `is_global: true` when the caller was an `ADMIN`.

### 2.2 `body_text` placeholders

`body_text` is formatted (Python `str.format`) with these values at render time — use any subset,
any number of times:

| Placeholder | Resolves to |
|---|---|
| `{student_name}` | The recipient's full name. |
| `{course_title}` | The completed course's title, as it was at the moment of completion. |
| `{completion_date}` | The issue date, formatted like `"August 23, 2026"`. |
| `{instructor_name}` | The course's instructor's full name. |
| `{organization_name}` | This template's own `organization_name` field. |

A typo'd or unknown placeholder (e.g. `{cours_title}`) will cause rendering to fail the first time
anyone tries to view that course's certificate — double check spelling before assigning a template
to a live course.

### 2.3 `border_style` options

| Value | Look |
|---|---|
| `CLASSIC` (default) | An ornate double frame — a thick primary-color outer line, a slim accent-color inset line, and small corner flourishes. The traditional "diploma" look. |
| `MODERN` | A single clean accent-color rectangle border. Minimal. |
| `NONE` | No border at all — just the background and content. |

### 2.4 List templates available to you

**`GET /certificates/templates?page=1&page_size=20`**

Returns your own templates **plus** every global template, newest first. If you're an `ADMIN`, this
returns *every* template in the system (all instructors' + global).

```json
{
  "success": true,
  "message": "OK",
  "data": [
    { "id": "...", "name": "Classic Achievement", "is_global": true, "owner_id": null, "...": "..." },
    { "id": "...", "name": "My Bootcamp Cert", "is_global": false, "owner_id": "your-uuid", "...": "..." }
  ],
  "meta": { "page": 1, "page_size": 20, "total_items": 2, "total_pages": 1, "has_next": false, "has_previous": false }
}
```

### 2.5 Get / update / delete a template

**`GET /certificates/templates/{template_id}`** — `403` if it's another instructor's private
template (global templates are always readable by any admin/instructor).

**`PATCH /certificates/templates/{template_id}`** — partial update
(`CertificateTemplateUpdateDTO`), any subset of the fields from §2.1 plus `is_active` (bool).
Setting `is_active: false` doesn't delete the template — it just removes it from the fallback pool
(§1) and stops it being used for **new** issuances; existing already-issued certificates that used
it are unaffected (they keep their already-rendered PDF, or re-render from whatever template is
still resolvable if not yet rendered — see student doc §2). Only the owner (or an admin) may
update; `403` otherwise, `404` if it doesn't exist.

```json
{ "accent_color": "#B8860B", "footer_text": "Verify this certificate online." }
```
```json
{ "success": true, "message": "Certificate template updated successfully", "data": { "...": "..." } }
```

**`DELETE /certificates/templates/{template_id}`** — soft-delete. Same ownership rule as update.
Courses pointing at a deleted template automatically fall back to the global default (§1) the next
time their certificate is resolved — you don't need to unassign it from courses first.

### 2.6 Upload a logo / signature image

Both use the same pre-signed-upload pattern as a course thumbnail: you get a short-lived `PUT` URL,
upload the raw file bytes to it directly (the file never passes through this API), and the
template's URL field is set immediately (optimistically) — no separate "finalize" call needed.

**`POST /certificates/templates/{template_id}/logo-upload-url`**
**`POST /certificates/templates/{template_id}/signature-upload-url`**

### Request body — `CertificateImageUploadRequestDTO`

| Field | Type | Notes |
|---|---|---|
| `file_name` | string | Used to build the storage key; keep the original extension (`.png`, `.jpg`). |
| `content_type` | string \| null | e.g. `"image/png"`. Passed through to the pre-signed URL so the upload's `Content-Type` header matches. |

### Response — `CertificateImageUploadResponseDTO`

```json
{
  "success": true,
  "message": "Logo upload URL generated successfully",
  "data": {
    "upload_url": "https://....r2.cloudflarestorage.com/....?X-Amz-Signature=...",
    "image_url": "https://pub-....r2.dev/certificate-templates/8e47937e-.../....-logo.png"
  }
}
```

Next step (client-side, not this API): `PUT` the raw image bytes to `upload_url` with the same
`Content-Type` you sent. `image_url` is already saved on the template (as `logo_url` /
`signature_image_url`) and is what gets embedded on the certificate — a broken/unreachable image at
render time is skipped gracefully rather than failing the whole certificate.

- **Logo**: rendered centered near the top of the certificate, above the organization name.
- **Signature image**: rendered above the signature line, on the left, alongside
  `signature_name`/`signature_title`.

Uploading again (same or different file) simply overwrites the URL — there's no gallery of past
uploads to manage.

---

## 3. Assigning a template to a course / toggling certificates

**`PATCH /certificates/courses/{course_id}/settings`**

Requires the caller to own the course (or be admin) — the same `ensure_can_manage` rule as every
other course-management endpoint (`403` otherwise, `404` if the course doesn't exist).

### Request body — `CourseCertificateSettingsUpdateDTO`

| Field | Type | Notes |
|---|---|---|
| `certificate_enabled` | bool \| null | Omit to leave unchanged. `false` stops certificates being issued for this course going forward — existing already-issued certificates are untouched. |
| `certificate_template_id` | UUID \| null | Assign a specific template. Must be a global template, or one you own (`403` if you try to use another instructor's private template) — admins can assign any template. |
| `clear_template` | bool | Default `false`. Set `true` to explicitly **unset** the course's template (falls back to the global default, §1) — this takes priority over `certificate_template_id` if both are sent. |

### Examples

Assign a specific template:
```json
{ "certificate_template_id": "8e47937e-e0c0-4932-8e32-c6dc3ad36b2e" }
```

Turn certificates off for this course entirely:
```json
{ "certificate_enabled": false }
```

Unassign (go back to whatever the global default is):
```json
{ "clear_template": true }
```

### Response
```json
{ "success": true, "message": "Course certificate settings updated successfully" }
```

`certificate_enabled` is also readable (and settable) directly on the normal course object now —
see [`COURSE_CONTENT_ENHANCEMENTS_INSTRUCTOR_ADMIN_API.md`](./COURSE_CONTENT_ENHANCEMENTS_INSTRUCTOR_ADMIN_API.md#2-certification-eligibility-toggle-certificate_enabled)
for the `POST /courses` / `PATCH /courses/{id}` / `GET /courses/manage/{id}` shape. `certificate_template_id`
still isn't echoed back anywhere — this settings endpoint remains the only way to read/set it; if you
need to confirm what's assigned, re-send the same values you intend (it's idempotent).

Also note: **new courses now default to `certificate_enabled: false`** (flipped from `true`) — a
course with continuous/ongoing content updates shouldn't hand out certificates for a moving target.
Instructors opt in explicitly via either this endpoint or the general course create/update payload.
Existing courses created before this change keep whatever value they already had.

---

## 4. Error responses you should handle

| Status | When |
|---|---|
| `403` | Not the template's owner (and not admin) on get-for-manage/update/delete/logo-upload/signature-upload; not the course's owner (and not admin) on the settings endpoint; assigning another instructor's private template to your course. |
| `404` | `template_id` or `course_id` doesn't exist. |
| `422` | Standard FastAPI validation error (bad hex color length, `name` too long, etc). |

---

## 5. End-to-end example: standing up a template and putting it on a course

```http
POST /certificates/templates
{ "name": "Bootcamp Gold", "accent_color": "#B8860B", "border_style": "MODERN" }
→ 201, data.id = "template-1"

POST /certificates/templates/template-1/logo-upload-url
{ "file_name": "logo.png", "content_type": "image/png" }
→ 201, data.upload_url = "...", data.image_url = "https://pub-.../....png"
(client PUTs the logo bytes to upload_url)

PATCH /certificates/courses/{course_id}/settings
{ "certificate_template_id": "template-1" }
→ 200
```

Every student who completes that course from now on gets a certificate rendered with this design —
nothing further to do on your side.

## 6. Seeding a default template (local/dev)

A ready-made "Classic Achievement" global template (with a procedurally generated emblem logo) can
be seeded via:

```bash
python -m app.scripts.seed_certificate_template --sample-out sample_certificate.pdf
```

Re-running it updates the same template in place (matched by name) rather than creating duplicates
— handy for iterating on the default design. `--sample-out` is optional and just renders a demo PDF
against dummy data so you can eyeball the design without needing a real completed course.
