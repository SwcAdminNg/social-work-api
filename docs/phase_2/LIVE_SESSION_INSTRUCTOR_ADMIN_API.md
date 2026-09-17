# Live Session — Instructor/Admin API Reference

This document covers a new curriculum item type, **`LIVE_SESSION`**: a scheduled real-time video
call (powered by daily.co) that enrolled students join at a set date/time, optionally featuring a
named guest speaker, with automatic student email notifications, calendar invites, and cloud
recording. It joins the existing `VIDEO`, `DOCUMENT`, `ASSESSMENT`, and `LINKS` item types as a
fifth first-class curriculum item.

This is the companion doc to [`LIVE_SESSION_STUDENT_API.md`](./LIVE_SESSION_STUDENT_API.md), which
covers how this shows up for students. Base URL prefix for everything below: `/courses`.

> ℹ️ Global response quirk: the API strips null/absent fields from JSON output. If a field isn't in
> the response, treat it as `null`/unset — don't treat its absence as an error.

---

## Conventions

- **Auth**: unless noted otherwise, every endpoint below requires `Authorization: Bearer <token>`
  for `ADMIN` or the course's owning `INSTRUCTOR` (`get_current_admin_or_instructor` +
  `ensure_can_manage`).
- **Response envelope**: `ApiResponse<T>` — `{ "success": true, "message": "...", "data": {...} }`.
- **Null stripping**: absent/null fields are stripped from JSON responses.
- **Times**: send/receive `scheduled_start_at` as ISO 8601 with timezone. Store and display in UTC;
  convert to the instructor's local timezone only for display.

---

## User stories

- *As an instructor,* when I want to run a live Q&A or workshop for my course, I want to schedule it
  as a normal curriculum item — same builder I use for videos and documents — rather than setting up
  a separate meeting tool and pasting a link into a text field.
- *As an instructor,* when I bring in a guest speaker for one specific session, I want to name them
  on that session so students know who they're hearing from, without that guest needing a platform
  account (same pattern as guest lecturers on a course section).
- *As an instructor,* the moment I schedule a session, I want every enrolled student notified by
  email automatically — with a calendar invite — so I don't have to separately announce it.
- *As an instructor,* if I need to move a session's time, I want students automatically told about
  the change (old time vs. new time) instead of silently updating a date field they might not notice.
- *As an instructor,* I want the session recorded automatically so students who couldn't attend can
  catch up later, without me needing to manually start/upload a recording.
- *As an admin,* I want live sessions to respect the exact same enrollment/ownership rules as every
  other curriculum item — I shouldn't need a separate permission model to reason about.
- *As an instructor,* I sometimes need to bring in someone who isn't enrolled — or doesn't have a
  platform account at all — to attend one specific session (an external panelist, a guest from a
  partner organization, a prospective student sitting in). I want to invite them by email and have
  them land straight in the call, without creating them a user account first, and it shouldn't
  matter whether I do this before the session or after it's already started.

---

## 1. How it works (mental model)

- A `LIVE_SESSION` curriculum item is created the same way as any other item — via the existing
  section/item builder — with `item_type: "LIVE_SESSION"`.
- On creation, the backend automatically:
  1. Creates a private daily.co video room scheduled for the given time window.
  2. Emails every currently-enrolled student a "session scheduled" notice with a join link, a
     calendar invite (`.ics`) and one-click "Add to Google/Outlook Calendar" links.
  3. Schedules a reminder email (default: 60 minutes before start) to go out automatically.
- Editing the schedule (`scheduled_start_at`/`duration_minutes`) before the session starts
  re-notifies every enrolled student with a "rescheduled" email and reschedules the reminder.
- The room is private — only enrolled students and the instructor/admin can obtain a join link (see
  the student doc's §2 for the join flow itself; that endpoint isn't one you call from the authoring
  side).
- **The call itself runs on daily.co's own hosted page** (their `socialworknigeria.daily.co`
  subdomain) — it's intentionally not embedded inside the student platform. The frontend's only job
  is to fetch a per-user join URL and redirect the browser there; there's no in-app video call UI to
  build or maintain.
- Cloud recording is enabled automatically on every session, **stored on daily.co's own cloud
  storage** — nothing is copied into your R2 bucket. Once the call ends and daily.co finishes
  processing, `recording_status` on the item flips to `READY` with no manual step on your side. A
  playable URL isn't stored anywhere (daily.co only issues short-lived signed links, not a permanent
  one) — see §7 for how the student side gets one on demand.
- Deleting the item deletes the underlying daily.co room too — no orphaned rooms to clean up
  manually.

---

## 2. Creating a live session item

**`POST /courses/{course_id}/sections/{section_id}/items`**

```json
{
  "title": "Live Q&A: Crisis Intervention Techniques",
  "item_type": "LIVE_SESSION",
  "order_index": 4,
  "scheduled_start_at": "2026-09-20T15:00:00Z",
  "duration_minutes": 60,
  "guest_name": "Dr. Amara Okafor",
  "guest_title": "Clinical Director, Crisis Response Network"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `scheduled_start_at` | ISO 8601 datetime | **Required** for `LIVE_SESSION`. | Must be in the future — `400 Bad Request` ("scheduled_start_at must be in the future") otherwise. |
| `duration_minutes` | int (5–600) | Optional | Defaults to `60` if omitted. |
| `guest_name` | string (max 255) | Optional | Named guest/lecturer for this specific session, distinct from the course's regular instructor(s) or section guest lecturers. Leave unset for a session run by the regular instructor. |
| `guest_title` | string (max 255) | Optional | E.g. `"Clinical Director, Crisis Response Network"`. Only meaningful alongside `guest_name`. |

Sending `scheduled_start_at`/`duration_minutes`/`guest_name`/`guest_title` on any other `item_type`
is a no-op — ignored, matching how `file_name` is ignored on non-`DOCUMENT` items.

The common item fields (`title`, `order_index`, `is_preview`, `estimated_minutes`) work exactly the
same as for every other item type — e.g. `is_preview: true` lets non-enrolled visitors see the
session's schedule/guest info on the public course page, same rule as a preview video/document.

**What happens synchronously on this call:** the daily.co room is created, the `CourseLiveSession`
row is persisted, **and every currently-enrolled student is emailed immediately** (this happens
inline before the response returns — expect this call to take a bit longer than creating a `VIDEO`/
`DOCUMENT` item, roughly proportional to enrollment size). There's no draft/unpublished state for a
live session item today — creating it notifies students right away, so only create it once the
schedule is final.

**Response (`201`):**

```json
{
  "success": true,
  "message": "Item created successfully",
  "data": {
    "id": "item-uuid",
    "section_id": "section-uuid",
    "title": "Live Q&A: Crisis Intervention Techniques",
    "item_type": "LIVE_SESSION",
    "order_index": 4,
    "is_preview": false,
    "video_upload": null,
    "document_upload": null
  }
}
```

Unlike `VIDEO`/`DOCUMENT`, there's no upload-credentials step — the item is immediately fully set
up. Fetch `GET /courses/manage/{course_id}` afterward (or the create/list endpoints, once populated)
to see the resolved `live_session` object with the daily.co room details.

---

## 3. Updating a live session item

**`PATCH /courses/items/{item_id}`**

```json
{
  "scheduled_start_at": "2026-09-22T15:00:00Z",
  "duration_minutes": 90,
  "guest_name": "Dr. Amara Okafor",
  "guest_title": "Clinical Director, Crisis Response Network"
}
```

- Send any subset — standard partial-update (`PATCH`) semantics, omit fields you're not changing.
- Only valid on a `LIVE_SESSION` item — sending these fields on any other item type returns
  `400 Bad Request` ("This item is not a live session").
- **Only editable while the session's `status` is `SCHEDULED`.** Once it's `LIVE`, `ENDED`, or
  `CANCELLED`, attempting to change `scheduled_start_at`/`duration_minutes`/`guest_name`/
  `guest_title` returns `400 Bad Request` ("This live session can no longer be edited").
- **Changing `scheduled_start_at` to a new value triggers a reschedule:**
  - The daily.co room's join window is updated to match.
  - Every enrolled student is emailed a "rescheduled" notice (old time struck through, new time,
    fresh calendar invite) — synchronously, same caveat as creation above.
  - The pending reminder is rescheduled to fire relative to the new time.
  - The new `scheduled_start_at` must still be in the future, or you get `400 Bad Request`.
- Changing only `duration_minutes`/`guest_name`/`guest_title` (without changing
  `scheduled_start_at`) updates the record silently — **no re-notification email is sent** for those
  alone. If you're changing the guest speaker and want students to know, change the title/description
  of the item itself (which isn't independently notified either) or communicate it through another
  channel — there's currently no "guest changed" email.
- Title/order/preview/estimated-minutes fields on the same `PATCH` work exactly as they do for every
  other item type (unaffected by anything above).

---

## 4. Deleting a live session item

**`DELETE /courses/items/{item_id}`** — works exactly as it does for any other item type, with one
extra side effect: the underlying daily.co room is deleted first, so you don't accumulate unused
rooms in your daily.co account. No student notification is sent on delete (matching the behavior for
deleting any other item type today).

---

## 5. Reading it back

Appears on the `live_session` object wherever curriculum items are returned — item list, `GET
/courses/manage/{id}`, `GET /courses/{slug}`:

```json
{
  "id": "item-uuid",
  "title": "Live Q&A: Crisis Intervention Techniques",
  "item_type": "LIVE_SESSION",
  "order_index": 4,
  "is_preview": false,
  "live_session": {
    "scheduled_start_at": "2026-09-20T15:00:00Z",
    "duration_minutes": 60,
    "guest_name": "Dr. Amara Okafor",
    "guest_title": "Clinical Director, Crisis Response Network",
    "status": "SCHEDULED",
    "recording_status": null
  }
}
```

| Field | Notes |
|---|---|
| `status` | `SCHEDULED` → `ENDED` (set automatically once daily.co reports the call ended). `LIVE` and `CANCELLED` are defined on the enum but not currently reachable via any code path today — a session stays `SCHEDULED` for its entire actual call duration (there's no explicit "now live" transition), and there's no "cancel" action; deleting the item is the way to call off a session before it happens. |
| `recording_status` | `null` until the call has happened; then `PENDING`/`PROCESSING`/`READY`/`FAILED` as daily.co processes the cloud recording. Reuses the same status values as `VIDEO` items. |

**No `recording_playback_url`/playback field on this endpoint, on purpose.** daily.co doesn't hand
out a permanent playback URL — only short-lived signed links (expiring within hours). Exposing one
here would mean an external API call to daily.co on every curriculum fetch. `recording_status` just
tells the instructor a recording exists; getting an actual playable link happens on the *student*
side, on demand, via `GET /learning/courses/{course_id}/items/{item_id}` (see §7) — there's currently
no instructor-facing endpoint to preview the recording separately from what students see.

The **manage** view of this object is identical to the public one shown above — there's no
manage-only field like `bunny_video_guid`/`storage_key` on video/document, since there's no
equivalent "internal identifier" instructors need (the daily.co room name isn't exposed via this
API).

---

## 6. Notifications and calendar invites (automatic — nothing to call)

Everything below fires server-side; there's no endpoint you call to "send the invite" — it's a side
effect of create/reschedule described in §2/§3.

| Trigger | Email sent to | Contents |
|---|---|---|
| Item created | Every currently-enrolled student | Date/time, guest info (if set), join link, "Add to Google Calendar"/"Add to Outlook" links, `.ics` attachment. |
| `scheduled_start_at` changed | Every currently-enrolled student | Old time (struck through) + new time, join link, updated calendar links/`.ics`. |
| ~60 minutes before start (configurable via the `LIVE_SESSION_REMINDER_MINUTES` server setting, not an API parameter) | Every currently-enrolled student | "Starting soon" with a prominent join button. |

Notes:
- "Currently-enrolled" is evaluated **at send time** — a student who enrolls *after* the item was
  created won't get the original "scheduled" email retroactively, but will see the item normally on
  the curriculum and will get the reminder email if they're enrolled by the time it fires.
- The calendar invite is a universal `.ics` file plus plain calendar-provider links — no student- or
  instructor-side Google/Outlook account connection is required for this to work.
- If the notification email fails to send for an individual student (e.g. bad address), it's logged
  server-side and does **not** fail the create/update API call — the item is still created/updated
  successfully either way.

---

## 7. Recording lifecycle and where the file actually lives

1. Recording starts automatically when the call begins (cloud recording is enabled on every room by
   default — no setting to toggle it per session today).
2. When the call ends, `status` flips to `ENDED` automatically.
3. Once daily.co finishes processing the recording (usually within a few minutes of the call ending),
   `recording_status` flips to `READY` — no polling endpoint needed on your side; just re-fetch the
   item like you would for any other content update.
4. If recording processing fails, `recording_status` becomes `FAILED`.

**The recording file is stored on daily.co's own cloud storage — not your Cloudflare R2 bucket.**
Unlike `VIDEO`/`DOCUMENT` items, there's no copy of this file under your own storage/CDN. daily.co
also doesn't hand out a permanent playback URL for it, only short-lived signed links (their default
is a 1-hour validity, capped at 7 days), so the API mints a fresh one on demand rather than storing
one:

- `GET /learning/courses/{course_id}/items/{item_id}` (the student-facing single-item endpoint)
  calls daily.co's `/recordings/{id}/access-link` endpoint fresh on every request and returns the
  result as `live_session_recording_url`, valid for `daily_recording_link_expire_seconds` (server
  config, default 6 hours).
- Nothing is cached — every request to that endpoint is a live network call to daily.co when a
  recording exists. There's currently no endpoint that returns a *stored* playback URL, by design.

**Retention is governed by your daily.co plan, not by this API.** How long daily.co keeps a cloud
recording before deleting it depends on your daily.co account/plan settings — this integration
doesn't currently download or archive recordings into your own storage. If you need recordings kept
indefinitely (independent of daily.co's retention policy) or served from your own domain/CDN like
`VIDEO` items are, that's a follow-up feature (download-and-re-upload-to-R2 on the
`recording.ready-to-download` webhook), not something built today — flag it if that's a requirement.

There's currently no endpoint to manually trigger/retry a recording, or to disable recording for a
specific session — treat every live session as "always recorded."

---

## 8. Endpoint reference summary

| Endpoint | What's new |
|---|---|
| `POST /courses/{course_id}/sections/{section_id}/items` | `item_type` accepts `"LIVE_SESSION"`. Body accepts `scheduled_start_at` (required), `duration_minutes`, `guest_name`, `guest_title` (LIVE_SESSION only). Creates a daily.co room and emails enrolled students synchronously. |
| `PATCH /courses/items/{item_id}` | Body accepts `scheduled_start_at`, `duration_minutes`, `guest_name`, `guest_title` (LIVE_SESSION only, only while `status: "SCHEDULED"`). Changing `scheduled_start_at` re-notifies enrolled students. |
| `DELETE /courses/items/{item_id}` | Also deletes the underlying daily.co room for a LIVE_SESSION item. |
| `GET /courses/manage/{id}`, `GET /courses/{slug}`, item-create response | Item objects include a new `live_session` object for `LIVE_SESSION` items. |
| `POST /courses/items/{item_id}/live-session/guests` | **New.** Invites one or more people (by email, no platform account required) to this specific session. See §10. |
| `GET /courses/items/{item_id}/live-session/guests` | **New.** Lists every guest invite for this session (invited/joined/revoked status). See §10. |
| `DELETE /courses/items/{item_id}/live-session/guests/{invite_id}` | **New.** Revokes a guest invite. See §10. |

---

## 9. Error responses you should handle

| Status | When |
|---|---|
| `400` | `scheduled_start_at` missing or not in the future when creating/rescheduling a `LIVE_SESSION` item. `scheduled_start_at`/`duration_minutes`/`guest_name`/`guest_title` sent in a `PATCH` for a non-live-session item, or for a live session that's no longer `SCHEDULED`. Inviting/listing/revoking guests on a session that's `ENDED`/`CANCELLED` (invite only — see §10). |
| `403` | Not the course's owner (and not admin) on any section/item management endpoint (unchanged, pre-existing rule) — this also covers the guest-invite endpoints in §10. |
| `404` | Course/section/item id doesn't exist (unchanged, pre-existing rule). Also: an `invite_id` that doesn't exist or belongs to a different session. |
| `422` | Standard FastAPI validation error (e.g. `duration_minutes` outside 5–600, `guest_name` over 255 chars, malformed datetime). |

---

## 10. Inviting guest/external attendees (no platform account required)

Separate from the named `guest_name`/`guest_title` credited on the invite email (§2) — this is an
actual **access grant** for people attending the call who aren't enrolled, and may not have an
account on the platform at all (an external panelist, someone from a partner organization, a
prospective student sitting in, etc.). They join via a personal emailed link, not by logging in.

**Works whether the session has started or not.** You can invite people before the session, and also
after it's already underway (`live_session_can_join: true`) — the only thing that blocks an invite is
the session already being `ENDED`/`CANCELLED`, since there's nothing left to join at that point.

**`POST /courses/items/{item_id}/live-session/guests`**

```json
{
  "invites": [
    { "email": "external.panelist@example.org", "name": "Dr. Chidi Nwosu" },
    { "email": "prospective.student@example.com" }
  ]
}
```

- `invites` — 1 to 100 entries per call.
- `email` — required, validated as a real email address.
- `name` — optional. Used for the invite email's greeting and as the attendee's display name on
  daily.co's call UI (falls back to their email if omitted).
- **Re-inviting an already-invited email is safe and idempotent** — it rotates their join link (the
  old link stops working) and un-revokes them if they'd been revoked, rather than creating a
  duplicate invite. Use this to resend a lost invite email.
- `400 Bad Request` ("This live session has already ended") if the session's `status` is `ENDED` or
  `CANCELLED`.
- Each successful invite triggers an email (date/time, a "Join Live Session" button, calendar
  links, `.ics` attachment) — same visual pattern as the student-facing scheduled/reminder emails, but
  worded for someone without an account. **If the email fails to send for one recipient** (bad
  address, provider outage), it's logged server-side and does **not** fail the rest of the batch —
  other recipients in the same call still get invited/emailed, and the failed one still gets a row in
  the response (retry by re-inviting the same email later).

**Response (`200`):**

```json
{
  "success": true,
  "message": "Guest invites sent successfully",
  "data": [
    {
      "id": "invite-uuid",
      "live_session_id": "live-session-uuid",
      "email": "external.panelist@example.org",
      "name": "Dr. Chidi Nwosu",
      "invited_by_id": "your-user-uuid",
      "expires_at": "2026-09-20T16:30:00Z",
      "revoked_at": null,
      "last_joined_at": null,
      "join_count": 0,
      "created_at": "2026-09-18T09:00:00Z"
    }
  ]
}
```

`expires_at` matches the session's own join window close (30 minutes after the scheduled end) — the
invite is only ever valid for *this* occurrence of the session, not reusable for a future one.

**`GET /courses/items/{item_id}/live-session/guests`** — lists every invite for this session (same
shape as above), most recently created first. Use `last_joined_at`/`join_count` to see who actually
showed up, and `revoked_at` to see who's been cut off.

**`DELETE /courses/items/{item_id}/live-session/guests/{invite_id}`** — revokes one invite
immediately; the raw link they were emailed stops working on their next join attempt (`400 Bad
Request`, `"This invite has been revoked"`). Doesn't un-send the original email — if you need them to
never have had access at all, this only prevents *further* joins.

**No raw token is ever returned by these endpoints** — the join link is only ever delivered via the
invite email, same convention as password-reset/admin-invite links elsewhere in the API. There's no
"copy invite link" affordance to build from this response; if a guest needs to be re-sent it, re-call
the invite endpoint with their email.

### How the guest actually joins

The guest never logs in. Their emailed link points at:

```
{FRONTEND_URL}/live-session/guest-join?token=<opaque-token>
```

Your frontend needs a public page (no auth-gate) at that route which, on load, calls:

**`GET /courses/live-session/guest-join?token=<opaque-token>`** — public, no `Authorization` header.

**Response (`200`):**

```json
{
  "success": true,
  "message": "Join credentials generated successfully",
  "data": {
    "join_url": "https://socialworknigeria.daily.co/session-abc123-f9e8d7c6?t=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "expires_at": "2026-09-20T16:30:00Z"
  }
}
```

Same shape as the authenticated join response (§ student doc, §3), minus `is_owner` — a guest is
never a call owner/moderator. Redirect the browser to `join_url` immediately, same as the
authenticated flow — don't pre-fetch and hold onto it.

**Error responses on the guest-join endpoint:**

| Status | When |
|---|---|
| `404` | Token doesn't match any invite (wrong/mistyped/already-superseded-by-a-resend token), or the underlying live session no longer exists. |
| `400` | `"This invite has been revoked"` — an admin/instructor revoked it. `"This invite link has expired"` — past the session's join window close, or the invite's own `expires_at`. `"This live session hasn't opened for joining yet"` — same 10-minutes-before-start rule as the authenticated flow; a guest can't join early either. `"This live session has ended"` (session cancelled). |

The join window rules are otherwise identical to the authenticated join flow (§ student doc, §3):
opens 10 minutes before `scheduled_start_at`, closes 30 minutes after the scheduled end. Inviting
someone doesn't bypass this window — it only controls *who* is allowed to attempt the join, not *when*.

---

## 11. Frontend implementation checklist

- [ ] Add `"LIVE_SESSION"` as a selectable item type in the curriculum builder, with its own form:
  a date/time picker (`scheduled_start_at`, required), a duration field (`duration_minutes`, minutes,
  default 60), and optional `guest_name`/`guest_title` text fields.
- [ ] Warn the instructor before submitting that creating the item **immediately emails every
  enrolled student** — make sure the schedule is final before they hit save (there's no draft mode).
- [ ] Curriculum item list rendering: handle `item.live_session` the same way you already handle
  `item.video`/`item.document`/`item.link`/`item.assessment` — pick the icon/renderer based on
  `item_type === "LIVE_SESSION"`.
- [ ] Edit form: lock the schedule fields (or show a clear warning) once `live_session.status` isn't
  `"SCHEDULED"` — the API will reject the change anyway, so fail gracefully in the UI first.
- [ ] When editing, clearly warn that changing the date/time **re-notifies every enrolled student**
  with a "rescheduled" email — this isn't a silent save.
- [ ] After a session ends, surface `recording_status` on the instructor's view of the item too, so
  they can confirm a recording is ready without asking students. To actually preview it, reuse the
  student-facing `GET /learning/courses/{course_id}/items/{item_id}` endpoint's
  `live_session_recording_url` — there's no separate instructor preview endpoint.
- [ ] Double-check any place you hardcode/switch on `item_type` values (e.g. an enum/union type in
  your frontend code) to make sure `"LIVE_SESSION"` doesn't silently fall through to a default/
  unknown state.
- [ ] Add an "Invite guests" action on the live session item's management view (available regardless
  of `status` being `SCHEDULED` or the session already being live — only disable it once `ENDED`/
  `CANCELLED`) — a simple email(+name) list input, posting to §10's invite endpoint.
- [ ] Show the invited-guests list (§10's `GET .../guests`) with `last_joined_at`/`join_count` so the
  instructor can see who actually attended, and a "Revoke" action per row.
- [ ] Build the public `/live-session/guest-join?token=...` landing page (§10) — no auth-gate, no
  login/signup prompt. It should call the guest-join endpoint on load and redirect to `join_url`,
  the same "thin redirector" pattern as the authenticated join page, but never asking the visitor to
  sign in.
