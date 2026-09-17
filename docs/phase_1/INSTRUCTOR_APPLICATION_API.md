# Instructor Application & Onboarding API Reference

Instructors are **not** created through `POST /auth/signup` — that endpoint now rejects
`user_type: "INSTRUCTOR"` (and `"ADMIN"`) outright. Becoming an instructor is a
review-gated flow: a candidate applies with their details and a CV, an admin approves or
rejects the application, and only on approval does the candidate get an emailed link to
finish setting up their account (username, password, and two-factor auth).

This document covers both halves of the flow:

- **§1–§3** — the public-facing application + account-setup endpoints (no login needed).
- **§4** — the admin-only review endpoints.
- **§5** — the full end-to-end user story, for building the actual screens.
- **§6** — error cases.

Base URL prefixes: `/instructor-applications` (public) and
`/admin/instructor-applications` (admin, `Authorization: Bearer <admin access token>`
required on every endpoint in §4).

## Conventions

- **Response envelope**: `ApiResponse<T>` — `{ "success": true, "message": "...", "data": {...} }`.
  Errors use the same shape with `"success": false` and no `data`.
- **Null stripping**: absent/null fields are stripped from JSON responses.
- **Pagination envelope** (list endpoint only): `{ "success", "message", "data": [...], "meta": { page, page_size, total_items, total_pages, has_next, has_previous } }`.

---

## 1. The mental model

```
                                    ┌────────────────────────┐
   Candidate                        │  1. Applies with CV     │
   (no account)          ─────────▶ │  POST /instructor-      │
                                    │  applications           │
                                    └───────────┬─────────────┘
                                                │  status: PENDING
                                                ▼
                                    ┌────────────────────────┐
   Admin                            │  2. Reviews it in the   │
   (dashboard)           ─────────▶ │  admin dashboard        │
                                    └───────────┬─────────────┘
                                    approve  ────┴────  reject
                                       │                  │
                                       ▼                  ▼
                          User row created,      Application marked
                          inactive, no            REJECTED. Rejection
                          password yet.           email sent. Flow ends
                          Setup email sent            here — no account
                          with a 7-day link.           is ever created.
                                       │
                                       ▼
                          ┌────────────────────────┐
   Candidate               │  3. Opens the emailed  │
   (clicks email link) ───▶│  link, sets username + │
                          │  password              │
                          │  POST /instructor-      │
                          │  applications/          │
                          │  complete-setup         │
                          └───────────┬─────────────┘
                                     │ same response shape as
                                     │ /auth/signup — see below
                                     ▼
                          ┌────────────────────────┐
                          │  4. Forced 2FA setup    │
                          │  (existing /auth/2fa/   │
                          │  setup/* endpoints —    │
                          │  see TWO_FACTOR_AUTH_   │
                          │  API.md)                │
                          └───────────┬─────────────┘
                                     ▼
                          Full session (user + tokens).
                          Account is now active and can log in normally
                          via /auth/login from then on.
```

Key facts your frontend needs to know up front:

- There is **no "reject with resubmit" loop inside the API** — a rejected candidate
  simply calls `POST /instructor-applications` again with a new payload. The API allows
  this (a prior `REJECTED` application never blocks a new one; only a currently-`PENDING`
  one does).
- The setup link **expires in 7 days**. If it expires (or is lost), the candidate cannot
  self-serve a new one — only an admin can, via the resend-link endpoint (§4.5).
- `complete-setup` does **not** log the instructor in directly. It returns the exact same
  `status: "two_factor_setup_required"` shape that `/auth/signup` and `/auth/login`
  return, so your existing forced-2FA-setup screens (built for signup) work here
  unmodified — see `docs/phase_1/TWO_FACTOR_AUTH_API.md` for that part.
- The instructor account is created (inactive, no password) **at approval time**, not at
  setup-completion time. Between approval and setup completion, the account cannot log
  in at all (no password is set).

---

## 2. Submitting an application (public, no auth)

**POST /instructor-applications**

```json
{
  "first_name": "Jane",
  "last_name": "Doe",
  "email": "jane.doe@example.com",
  "phone_number": "+2348012345678",
  "cv_file_name": "jane-doe-cv.pdf",
  "cv_content_type": "application/pdf"
}
```

| Field             | Type   | Required | Notes                                      |
|-------------------|--------|----------|---------------------------------------------|
| `first_name`      | string | yes      | 1–100 chars                                 |
| `last_name`       | string | yes      | 1–100 chars                                 |
| `email`           | string | yes      | valid email                                 |
| `phone_number`    | string | yes      | 1–20 chars, free-form                       |
| `cv_file_name`    | string | yes      | original filename, e.g. `"jane-cv.pdf"`     |
| `cv_content_type` | string | no       | MIME type, e.g. `"application/pdf"`         |

**201 Created:**

```json
{
  "success": true,
  "message": "Application submitted. Upload your CV using the provided URL.",
  "data": {
    "application_id": "5ff51e61-19b4-46a3-9fd9-25d66db37d5e",
    "upload_url": "https://<account>.r2.cloudflarestorage.com/social-work/instructor-applications/5ff51e61.../cv/....pdf?X-Amz-Algorithm=...",
    "storage_key": "instructor-applications/5ff51e61.../cv/19eaf8be-....pdf"
  }
}
```

**Immediately after this call**, the frontend must upload the actual CV file directly to
R2 using `upload_url` — a plain HTTP `PUT` with the file bytes as the body:

```js
await fetch(uploadUrl, {
  method: "PUT",
  headers: { "Content-Type": cvFile.type }, // must match cv_content_type sent above, if any
  body: cvFile,
});
```

- `upload_url` is a presigned S3-style URL, valid for **10 minutes** (`presigned_url_expire_seconds`).
  If the upload doesn't happen in time, there's no retry endpoint — the applicant must
  submit the application again (a fresh `POST /instructor-applications` mints a fresh
  URL and a fresh `application_id`).
- The application row is created **before** the CV upload happens. If the user abandons
  the flow after step 1, an admin reviewing the application will see it but the CV
  download will 404/empty on R2 — this is expected and not specially handled by the API.
- The API never touches the file bytes itself — nothing is uploaded through this server.
- `storage_key` is returned for completeness but the frontend has no direct use for it
  (it's the R2 object key, used internally for admin CV downloads later).

**Duplicate-guard responses** (same endpoint):

| Situation                                                    | Response                                                        |
|----------------------------------------------------------------|--------------------------------------------------------------------|
| Email already belongs to a registered user                     | `409` `"This email is already registered"`                        |
| Email already has a `PENDING` application under review          | `409` `"An application from this email is already under review"`  |

A `REJECTED` application for that email does **not** trigger the second guard — the
candidate can freely re-apply.

---

## 3. Completing account setup (public, called from the emailed link)

The approval email (see §4.3) contains a link shaped like:

```
{frontend_url}/instructor/complete-setup?token=<opaque-token>
```

Your frontend owns the `/instructor/complete-setup` page/route — build a form that reads
`token` from the query string and collects a username + password, then calls:

**POST /instructor-applications/complete-setup**

```json
{
  "token": "ubAG4iCUXmeLT3zOZK9JOf35NnfktQ8uHsKlEOaOB4U",
  "username": "jane.doe",
  "password": "SecurePass123!",
  "confirm_password": "SecurePass123!"
}
```

| Field              | Type   | Notes                                                                 |
|--------------------|--------|--------------------------------------------------------------------------|
| `token`            | string | from the query string, verbatim                                          |
| `username`         | string | 3–30 chars, lowercase letters/numbers/dots/underscores only (`^[a-z0-9_.]{3,30}$`); case-insensitive, lower-cased server-side |
| `password`         | string | 8–128 chars                                                               |
| `confirm_password` | string | must match `password`                                                    |

**200 OK** — same shape as `/auth/signup`:

```json
{
  "success": true,
  "message": "Account set up. Set up two-factor authentication to continue.",
  "data": {
    "status": "two_factor_setup_required",
    "challenge": { "challenge_token": "eyJhbGciOi..." }
  }
}
```

Take `challenge_token` straight into the existing forced-2FA-setup screens (TOTP or
email — see `docs/phase_1/TWO_FACTOR_AUTH_API.md` §4). Once 2FA setup is confirmed there,
the response is a normal `AuthSessionDTO` (`{ user, tokens }`) and the instructor is
fully logged in. `user.user_type` will be `"INSTRUCTOR"`.

**Error responses:**

| Situation                                            | Response                                       |
|--------------------------------------------------------|---------------------------------------------------|
| Token invalid, unknown, expired, or already used         | `400` `"Invalid or expired setup link"`            |
| Chosen username is already taken                          | `409` `"Username is already taken"`                |
| Username fails the pattern / password mismatch            | `422` (validation error, standard shape)           |

A used or expired token gives the frontend nothing to recover from client-side — the
correct UX is "This link has expired or was already used. Contact support for a new
one," since only an admin can issue a fresh link (§4.5).

---

## 4. Admin review endpoints

All require `Authorization: Bearer <admin access token>`.

### 4.1 List applications

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
for that (avoids minting a presigned URL per row on every page load).

Sorted newest-first (`created_at DESC`).

### 4.2 Get application detail (with CV download link)

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
time before clicking "Download CV").

**404** `"Instructor application not found"` if the id doesn't exist.

### 4.3 Approve

**POST /admin/instructor-applications/{application_id}/approve**

```json
{ "platform": "NG" }
```

`platform` is required — `"NG"` or `"COM"` (mirrors the existing platform split used
elsewhere in this API, e.g. admin invites). This determines which platform's instructor
account is created; pick based on which storefront/brand the applicant is applying to.

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
(`user_type: "INSTRUCTOR"`, `is_active: false`, no password, no real username yet — an
internal placeholder is used and is never shown to anyone), and an email is sent to the
applicant with a 7-day setup link. **The instructor cannot log in until they complete
setup** (§3).

Sending the email is best-effort: if the email provider hiccups, the approval still
succeeds (the user + setup token both exist) — the admin should use resend-link (§4.5)
if the applicant reports never receiving it.

**409** `"This application has already been reviewed"` if `status` isn't `PENDING`
(i.e. someone already approved or rejected it — a second click is a no-op error, not a
double-approval).

### 4.4 Reject

**POST /admin/instructor-applications/{application_id}/reject**

```json
{ "reason": "CV did not demonstrate relevant teaching experience" }
```

`reason` is optional (nullable) — if omitted, the rejection email is sent without a
specific reason shown to the applicant.

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

No `User` row is ever created for a rejected application. `user_id` is absent from the
response. **409** `"This application has already been reviewed"` under the same
conditions as approve.

### 4.5 Resend setup link

Use this when an approved applicant's 7-day link expired (or they say they never got
the email) and they still haven't finished setup.

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
|---------------------------------------------------------------------|------------------------------------------------------------|
| Application isn't `APPROVED` yet (still `PENDING` or `REJECTED`)      | `"This application has not been approved"`                 |
| The instructor already finished setup (has a password already)        | `"This instructor has already completed account setup"`    |

For the second case, the frontend should just tell the admin the instructor can already
log in normally — there's nothing to resend.

---

## 5. Full user story (for screen design)

**Applicant side:**

1. Visitor lands on a public "Become an Instructor" page/form (no login).
2. Fills first name, last name, email, phone, and attaches a CV file.
3. On submit: call §2, then immediately `PUT` the file to the returned `upload_url`.
   Show a clear "Application submitted!" confirmation — there is nothing else for them
   to do until they hear back by email. Handle the two 409 cases (§2) with friendly
   inline messages ("You already have an application under review" /
   "This email is already registered — try logging in instead").
4. Applicant waits (no polling/status page needed — they'll get an email either way).
5. **If approved**: they receive an email with a "Set Up My Account" button/link
   → lands on your `/instructor/complete-setup?token=...` page → form for
   username + password (+confirm) → call §3 → immediately continue into the existing
   2FA-setup screens using the returned `challenge_token` (same UI you already built for
   `/auth/signup`) → land in the full instructor dashboard, logged in.
6. **If rejected**: they receive an email explaining that, optionally with a reason.
   No API interaction needed on your side for this — it's purely informational. If you
   want a "re-apply" CTA in that email, just link back to the same public application
   form (§2) — nothing blocks a fresh submission.

**Admin side:**

1. Admin dashboard shows an "Instructor Applications" list (§4.1), filterable by status,
   defaulting to `PENDING` so new applications surface first.
2. Clicking a row opens a detail view (§4.2) with all fields plus a "Download CV" link
   (`cv_download_url` — opens/downloads directly from R2, no server round-trip).
3. From the detail view (only when `status === "PENDING"`), two actions:
   - **Approve** → prompts for `platform` (NG/COM) → calls §4.3 → show the success
     toast from the response `message`.
   - **Reject** → optional reason textarea → calls §4.4 → show the success toast.
4. For an `APPROVED` application where the admin knows (or the applicant reports) the
   link expired: a "Resend Setup Link" button on the detail view → calls §4.5. Consider
   disabling/hiding this once you know the instructor has completed setup (you can infer
   this from a separate instructor/user list, if the admin dashboard has one — this
   endpoint itself doesn't expose "has completed setup" directly beyond the 400 message
   if you try anyway).

---

## 6. Error cases (quick reference)

| Endpoint                                      | Situation                                             | Response |
|------------------------------------------------|--------------------------------------------------------|----------|
| `POST /instructor-applications`                 | Email already registered                                | `409` |
| `POST /instructor-applications`                 | Email has a pending application already                 | `409` |
| `POST /instructor-applications/complete-setup`  | Token invalid/expired/used                               | `400` |
| `POST /instructor-applications/complete-setup`  | Username taken                                           | `409` |
| Any `/admin/instructor-applications/{id}...`    | Application id doesn't exist                              | `404` |
| Approve / Reject                                | Application already reviewed (not `PENDING`)              | `409` |
| Resend-link                                     | Application not `APPROVED`                                 | `400` |
| Resend-link                                     | Instructor already completed setup                          | `400` |
| Any admin endpoint                              | Missing/invalid bearer token, or token belongs to non-admin | `401` / `403` |
| `POST /auth/signup`                             | `user_type: "INSTRUCTOR"` (or `"ADMIN"`) submitted           | `422` — "Admin and instructor accounts cannot be created via sign-up; ..." |
