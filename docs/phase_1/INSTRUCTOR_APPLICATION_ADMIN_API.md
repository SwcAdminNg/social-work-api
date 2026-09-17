# Instructor Application API Reference — Admin Side

Instructor accounts are gated behind admin review. A candidate applies through a public
form (see `INSTRUCTOR_APPLICATION_APPLICANT_API.md`) and uploads a CV; this document
covers everything an admin dashboard needs to review, approve, reject, and manage those
applications.

- **§1** — the mental model / where the admin fits in the flow.
- **§2** — list applications.
- **§3** — get application detail (with CV download).
- **§4** — approve.
- **§5** — reject.
- **§6** — resend the setup link.
- **§7** — the full user story, screen by screen.
- **§8** — error quick-reference.

Base URL prefix: `/admin/instructor-applications`. **Every endpoint below requires**
`Authorization: Bearer <admin access token>`.

## Conventions

- **Response envelope**: `ApiResponse<T>` — `{ "success": true, "message": "...", "data": {...} }`.
  Errors use the same shape with `"success": false` and no `data`.
- **Null stripping**: absent/null fields are stripped from JSON responses.
- **Pagination envelope** (list endpoint only): `{ "success", "message", "data": [...], "meta": { page, page_size, total_items, total_pages, has_next, has_previous } }`.

---

## 1. The mental model

```
   Applicant submits application + CV  (public flow, not this doc)
                    │
                    ▼  status: PENDING
   ┌─────────────────────────────────────────┐
   │  Admin dashboard: "Instructor            │
   │  Applications" list, filterable by       │
   │  status — GET /admin/instructor-         │
   │  applications                            │
   └───────────────────┬───────────────────────┘
                       │  click a row
                       ▼
   ┌─────────────────────────────────────────┐
   │  Detail view (fields + CV download) —    │
   │  GET /admin/instructor-applications/{id} │
   └─────────┬───────────────────┬─────────────┘
        Approve                Reject
             │                     │
             ▼                     ▼
   User row created,      Application marked
   inactive, no            REJECTED. Rejection
   password yet.           email sent. No account
   Setup email sent        is ever created. The
   with a 7-day link.      applicant may apply again
             │              freely at any time.
             ▼
   ┌─────────────────────────────────────────┐
   │  If the link expires (or the applicant   │
   │  says they never got it) before they     │
   │  finish setup: resend it —               │
   │  POST .../{id}/resend-link                │
   └─────────────────────────────────────────┘
```

Key facts your dashboard needs to know up front:

- Approving does **not** immediately activate the instructor — it creates the account
  and emails a setup link. The instructor can't log in until *they* complete setup
  (username + password + 2FA) on the applicant side.
- Approve/reject are **one-shot**: once an application is `APPROVED` or `REJECTED`,
  calling either endpoint again returns `409`. Build your UI so those buttons disappear
  (or the whole review panel goes read-only) once a decision has been made.
- Rejecting never creates a user account — there's nothing to "undo" beyond re-reviewing
  isn't possible; the applicant's only path forward is submitting a brand-new
  application.
- Sending the approval/rejection email is best-effort server-side — if the email
  provider hiccups, the approval or rejection still fully succeeds. If an applicant
  claims they never got the approval email, use resend-link (§6) rather than trying to
  re-approve (which will just 409).

---

## 2. List applications

**GET /admin/instructor-applications?status=PENDING&page=1&page_size=20**

- `status` (optional query param): `PENDING` | `APPROVED` | `REJECTED`. Omit to list all.
- `page` / `page_size`: standard pagination (`page_size` max 100).

```json
{
  "success": true,
  "message": "OK",
  "data": [
    {
      "id": "5ff51e61-19b4-46a3-9fd9-25d66db37d5e",
      "created_at": "2026-09-17T17:54:13.617479Z",
      "updated_at": "2026-09-17T17:54:13.617479Z",
      "first_name": "John",
      "last_name": "Smith",
      "email": "john.smith@example.com",
      "phone_number": "+2348011112222",
      "cv_file_name": "john-cv.pdf",
      "status": "PENDING"
    }
  ],
  "meta": { "page": 1, "page_size": 20, "total_items": 1, "total_pages": 1, "has_next": false, "has_previous": false }
}
```

Note the list view does **not** include `cv_download_url` — fetch the detail endpoint
(§3) for that (avoids minting a presigned URL per row on every page load).

Sorted newest-first (`created_at DESC`). Default your dashboard's initial filter to
`PENDING` so new applications surface first.

---

## 3. Get application detail (with CV download link)

**GET /admin/instructor-applications/{application_id}**

```json
{
  "success": true,
  "message": "Instructor application retrieved",
  "data": {
    "id": "5ff51e61-19b4-46a3-9fd9-25d66db37d5e",
    "created_at": "2026-09-17T17:54:13.617479Z",
    "updated_at": "2026-09-17T17:54:13.617479Z",
    "first_name": "John",
    "last_name": "Smith",
    "email": "john.smith@example.com",
    "phone_number": "+2348011112222",
    "cv_file_name": "john-cv.pdf",
    "status": "PENDING",
    "cv_download_url": "https://<account>.r2.cloudflarestorage.com/social-work/instructor-applications/.../john-cv.pdf?X-Amz-..."
  }
}
```

Once `status` is `APPROVED` or `REJECTED`, this response also includes `reviewed_by`
(admin user id), `reviewed_at` (timestamp), `user_id` (the created instructor's user id,
`APPROVED` only), and `rejection_reason` (`REJECTED` only, may be `null`).

`cv_download_url` is a fresh presigned GET URL, valid for **10 minutes** — regenerate by
re-calling this endpoint if it expires (e.g. the admin left the detail page open a long
time before clicking "Download CV"). Just open/download it directly from R2 — no server
round-trip needed.

**404** `"Instructor application not found"` if the id doesn't exist.

---

## 4. Approve

**POST /admin/instructor-applications/{application_id}/approve**

```json
{ "platform": "NG" }
```

`platform` is required — `"NG"` or `"COM"` (mirrors the existing platform split used
elsewhere in this API, e.g. admin invites). This determines which platform/storefront's
instructor account is created; pick based on which one the applicant is applying to. If
your dashboard only ever serves one platform, you can hardcode this rather than
prompting the admin.

**200 OK:**

```json
{
  "success": true,
  "message": "Application approved. The applicant has been emailed a setup link.",
  "data": {
    "id": "5ff51e61-19b4-46a3-9fd9-25d66db37d5e",
    "status": "APPROVED",
    "reviewed_by": "f14fd447-985a-4cdc-b73a-307565841fe9",
    "reviewed_at": "2026-09-17T17:59:03.961698Z",
    "user_id": "4c5841d6-c94b-46ec-af42-dd2b323ea596",
    "first_name": "John", "last_name": "Smith", "email": "john.smith@example.com",
    "phone_number": "+2348011112222", "cv_file_name": "john-cv.pdf"
  }
}
```

What happens server-side: a `User` row is created immediately
(`user_type: "INSTRUCTOR"`, `is_active: false`, no password, no real username yet — the
instructor picks their own username during setup), and an email is sent to the applicant
with a 7-day setup link.

**409** `"This application has already been reviewed"` if `status` isn't `PENDING` — a
second click (e.g. a double-submit) is a no-op error, not a double-approval. Disable the
Approve/Reject buttons optimistically after the first click to avoid this in normal use.

---

## 5. Reject

**POST /admin/instructor-applications/{application_id}/reject**

```json
{ "reason": "CV did not demonstrate relevant teaching experience" }
```

`reason` is optional (nullable) — if omitted, the rejection email is sent without a
specific reason shown to the applicant. Recommend always giving the admin a reason
textarea in the UI even though it's optional, since it improves the applicant experience.

**200 OK:**

```json
{
  "success": true,
  "message": "Application rejected. The applicant has been notified by email.",
  "data": {
    "id": "30d7102a-6c94-4542-a347-fb79a15ae35c",
    "status": "REJECTED",
    "rejection_reason": "CV did not demonstrate relevant teaching experience",
    "reviewed_by": "f14fd447-985a-4cdc-b73a-307565841fe9",
    "reviewed_at": "2026-09-17T17:59:21.530979Z",
    "first_name": "Chidi", "last_name": "Eze", "email": "chidi@example.com",
    "phone_number": "+2348088887777", "cv_file_name": "chidi-cv.pdf"
  }
}
```

No `User` row is ever created for a rejected application — `user_id` is absent from the
response. **409** `"This application has already been reviewed"` under the same
conditions as approve.

---

## 6. Resend setup link

Use this when an approved applicant's 7-day link expired (or they say they never got the
email) and they still haven't finished setup.

**POST /admin/instructor-applications/{application_id}/resend-link** (empty body)

**200 OK:**

```json
{
  "success": true,
  "message": "A fresh setup link has been emailed to the applicant",
  "data": { "message": "Setup link resent" }
}
```

This **invalidates the previous link** — if the old one wasn't actually expired yet
(e.g. admin resends just to be safe), it stops working the instant the new one is
issued. Only ever one active setup link per instructor at a time.

**400 error cases:**

| Situation                                                        | Message                                                     |
|---------------------------------------------------------------------|--------------------------------------------------------------|
| Application isn't `APPROVED` yet (still `PENDING` or `REJECTED`)      | `"This application has not been approved"`                   |
| The instructor already finished setup (has a password already)        | `"This instructor has already completed account setup"`      |

For the second case, tell the admin the instructor can already log in normally — there's
nothing to resend. Consider hiding the "Resend Link" action once you know setup is done
(e.g. via a separate instructor/user list showing `is_active: true`), and otherwise just
surface this 400's message directly if the admin tries anyway.

---

## 7. Full user story (for screen design)

1. Admin dashboard shows an "Instructor Applications" list (§2), filterable by status,
   defaulting to `PENDING` so new applications surface first.
2. Clicking a row opens a detail view (§3) with all applicant fields plus a "Download
   CV" link (`cv_download_url` — opens/downloads directly from R2, no server
   round-trip).
3. From the detail view, when `status === "PENDING"`, show two actions:
   - **Approve** → prompt for `platform` (NG/COM), or skip the prompt if your dashboard
     only serves one platform → calls §4 → show the success toast from the response
     `message` → the row/detail view flips to `APPROVED` and the approve/reject actions
     disappear.
   - **Reject** → optional reason textarea → calls §5 → show the success toast → row
     flips to `REJECTED`.
4. When `status === "APPROVED"`, show a "Resend Setup Link" action instead → calls §6.
   Handle the 400 cases from §6 with clear inline messaging rather than a generic error
   toast, since both are legitimate, expected states (not approved yet / already done).
5. When `status === "REJECTED"`, the detail view is read-only — show the stored
   `rejection_reason` if present, and no further actions are available for that
   application.

---

## 8. Error quick-reference

| Endpoint                                       | Situation                                                    | Response |
|---------------------------------------------------|------------------------------------------------------------------|----------|
| Any endpoint in this doc                            | Application id doesn't exist                                        | `404` |
| Approve / Reject                                    | Application already reviewed (not `PENDING`)                        | `409` |
| Resend-link                                         | Application not `APPROVED`                                          | `400` |
| Resend-link                                         | Instructor already completed setup                                   | `400` |
| Any endpoint in this doc                            | Missing/invalid bearer token, or token belongs to a non-admin user     | `401` / `403` |
