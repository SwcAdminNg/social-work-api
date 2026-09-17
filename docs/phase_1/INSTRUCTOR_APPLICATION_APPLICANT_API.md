# Instructor Application API Reference — Applicant Side

Instructors are **not** created through `POST /auth/signup` — that endpoint now rejects
`user_type: "INSTRUCTOR"` outright. Becoming an instructor is a review-gated flow: a
candidate applies with their details and a CV, an admin reviews it elsewhere (see
`INSTRUCTOR_APPLICATION_ADMIN_API.md`), and only on approval does the candidate get an
emailed link to finish setting up their account.

This document covers the two public, unauthenticated endpoints an applicant-facing
frontend needs:

- **§1** — the mental model / end-to-end flow.
- **§2** — submitting an application (with CV upload).
- **§3** — completing account setup from the emailed link.
- **§4** — the full user story, screen by screen.
- **§5** — error quick-reference.

Base URL prefix: `/instructor-applications`. Neither endpoint requires an
`Authorization` header.

## Conventions

- **Response envelope**: `ApiResponse<T>` — `{ "success": true, "message": "...", "data": {...} }`.
  Errors use the same shape with `"success": false` and no `data`.
- **Null stripping**: absent/null fields are stripped from JSON responses.

---

## 1. The mental model

```
   Candidate                        1. Applies with CV
   (no account)          ─────────▶ POST /instructor-applications
                                    │  status: PENDING
                                    ▼
                          (admin reviews — separate flow,
                           see the admin-side doc)
                                    │
                       approve  ────┴────  reject
                          │                  │
                          ▼                  ▼
              Setup email sent      Rejection email sent.
              with a 7-day link.    Flow ends here — no
                          │          account is ever created.
                          ▼          You're free to apply again
              2. Candidate opens     any time (§2 duplicate rules).
              the emailed link,
              sets username +
              password
              POST /instructor-
              applications/
              complete-setup
                          │  same response shape as
                          │  /auth/signup — see below
                          ▼
              3. Forced 2FA setup
              (existing /auth/2fa/
              setup/* endpoints —
              see TWO_FACTOR_AUTH_
              API.md)
                          ▼
              Full session (user + tokens).
              Account is now active and can log in normally
              via /auth/login from then on.
```

Key facts your frontend needs to know up front:

- There is **no "reject with resubmit" loop inside the API** — a rejected candidate
  simply calls `POST /instructor-applications` again with a new payload. A prior
  `REJECTED` application never blocks a new one; only a currently-`PENDING` one does.
- The setup link **expires in 7 days**. If it expires (or is lost), you cannot self-serve
  a new one from this side of the API — only an admin can reissue it. Direct the
  applicant to contact support if their link has gone stale.
- `complete-setup` does **not** log the instructor in directly. It returns the exact same
  `status: "two_factor_setup_required"` shape that `/auth/signup` and `/auth/login`
  return, so your existing forced-2FA-setup screens (built for signup) work here
  unmodified — see `docs/phase_1/TWO_FACTOR_AUTH_API.md` for that part.
- The instructor's account exists (inactive, no password) from the moment an admin
  approves — but it cannot log in at all until setup (§3) is completed.

---

## 2. Submitting an application

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

- `upload_url` is a presigned S3-style URL, valid for **10 minutes**. If the upload
  doesn't happen in time, there's no retry endpoint — the applicant must submit the
  application again (a fresh `POST /instructor-applications` mints a fresh URL and a
  fresh `application_id`).
- The application row is created **before** the CV upload happens. If the user abandons
  the flow after step 1, that's fine — it just leaves a pending application with a CV
  that never got uploaded, which the admin side handles gracefully.
- The API never touches the file bytes itself — nothing is uploaded through this server,
  it goes straight from the browser to R2.
- `storage_key` is returned for completeness but the frontend has no direct use for it.

**Duplicate-guard responses** (same endpoint):

| Situation                                                    | Response                                                        |
|----------------------------------------------------------------|--------------------------------------------------------------------|
| Email already belongs to a registered user                     | `409` `"This email is already registered"`                        |
| Email already has a `PENDING` application under review          | `409` `"An application from this email is already under review"`  |

A `REJECTED` application for that email does **not** trigger the second guard — the
candidate can freely re-apply.

---

## 3. Completing account setup (from the emailed link)

The approval email contains a link shaped like:

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
one." Only an admin can issue a fresh link.

---

## 4. Full user story (for screen design)

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
7. **If the setup link expires** before step 5 is completed: the applicant sees the
   "expired/used" error from §3. Direct them to contact support — an admin will use the
   resend-link endpoint on their side and a new email will arrive.

---

## 5. Error quick-reference

| Endpoint                                        | Situation                                       | Response |
|--------------------------------------------------|--------------------------------------------------|----------|
| `POST /instructor-applications`                   | Email already registered                          | `409` |
| `POST /instructor-applications`                   | Email has a pending application already            | `409` |
| `POST /instructor-applications/complete-setup`    | Token invalid/expired/used                         | `400` |
| `POST /instructor-applications/complete-setup`    | Username taken                                     | `409` |
| `POST /auth/signup`                               | `user_type: "INSTRUCTOR"` submitted                 | `422` — "Admin and instructor accounts cannot be created via sign-up; ..." |
