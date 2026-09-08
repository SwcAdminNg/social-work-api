# Live Session — Student/User API Reference

This document covers how enrolled students discover, join, and get notified about **Live
Sessions** — a new curriculum item type (`LIVE_SESSION`) that runs a real-time video call via
daily.co on a scheduled date/time, alongside the existing `VIDEO`, `DOCUMENT`, `ASSESSMENT`, and
`LINKS` types. It's the companion to
[`LIVE_SESSION_INSTRUCTOR_ADMIN_API.md`](./LIVE_SESSION_INSTRUCTOR_ADMIN_API.md), which covers how
instructors/admins schedule and manage them.

> ℹ️ Global response quirk: the API strips null/absent fields from JSON output. If a field isn't in
> the response, treat it as `null`/unset — don't treat its absence as an error.

---

## Conventions

- **Auth**: every endpoint below requires `Authorization: Bearer <token>` for an enrolled student
  (or the course's owning instructor/admin, for the join endpoint).
- **Response envelope**: `ApiResponse<T>` — `{ "success": true, "message": "...", "data": {...} }`.
- **Base URLs**: curriculum/course browsing is under `/courses`; active learning is under
  `/learning`. The join endpoint is under `/courses`.
- **Times**: `scheduled_start_at` and every other timestamp are ISO 8601 with timezone (UTC).
  Convert to the viewer's local timezone client-side before displaying.

---

## User stories

- *As a student,* when I open a course, I want to see any upcoming live sessions on the curriculum
  right alongside the videos and documents, with the date/time and who's presenting, so I can plan
  to show up.
- *As a student,* when a live session is scheduled, I want an email with the date/time, a "Join"
  button, and the option to add it straight to my Google/Outlook/Apple calendar in one click, so I
  don't have to remember it manually.
- *As a student,* when it's time for the session, I want to click "Join" and land in the video call
  without any extra sign-in step or pasted meeting ID — the platform already knows who I am and that
  I'm enrolled.
- *As a student,* if a session gets rescheduled, I want a clear "this moved" email showing the old
  and new times, with an updated calendar invite — not just a silent change I might miss.
- *As a student,* if I miss a live session (or want to rewatch it), I want to come back to the same
  curriculum item afterward and find a recording, the same way I'd rewatch any other video lesson.
- *As a student,* I should never be able to join a live session for a course I'm not enrolled in,
  even if I somehow get the link.
- *As a student,* I want one place to see every upcoming live session across all my enrolled
  courses — not have to open each course individually to check if something's scheduled — so I can
  plan my week, optionally narrowed to a specific date range (e.g. "this week", "this month").

---

## 1. Seeing live sessions on the curriculum

### Before enrolling — course browsing/detail

**`GET /courses/{slug}`** — a `LIVE_SESSION` item appears in the curriculum tree like any other item
type, subject to the same preview/enrollment gating that already applies to `video`/`document`/
`link`/`assessment` (full details only show if the item `is_preview: true` or you're enrolled):

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
    "recording_status": null,
    "recording_playback_url": null
  }
}
```

| Field | Notes |
|---|---|
| `live_session.scheduled_start_at` | ISO 8601 UTC timestamp. Render in the viewer's local time. |
| `live_session.duration_minutes` | Planned length of the call. |
| `live_session.guest_name` / `guest_title` | Optional named guest/lecturer for this specific session, distinct from the course's regular instructor(s). Both `null` when there's no guest — just show the course's normal instructor byline in that case. |
| `live_session.status` | `SCHEDULED` \| `LIVE` \| `ENDED` \| `CANCELLED`. In practice today a session only ever moves `SCHEDULED` → `ENDED` (set automatically once the call ends) — `LIVE` is a reserved value not currently set by any code path, and `CANCELLED` isn't settable via any endpoint yet. Rely on `live_session_can_join` (below), not `status`, to know whether "Join" should be active right now. |
| `live_session.recording_status` | `null` until a recording exists, then `PENDING` → `PROCESSING` → `READY` (or `FAILED`). Only meaningful once `status` is `ENDED`. |
| `live_session.recording_playback_url` | Populated once `recording_status: "READY"`. Render a normal video player, same as a `VIDEO` item's playback URL. |

`live_session` is `null`/absent for every other item type, same pattern as `video`/`document`/
`link`/`assessment`.

### While enrolled and studying — the learning endpoints

**`GET /learning/courses/{course_id}/curriculum`** — the lightweight outline only tells you an item
exists and its type; it doesn't carry live-session-specific fields:

```json
{
  "id": "item-uuid",
  "title": "Live Q&A: Crisis Intervention Techniques",
  "item_type": "LIVE_SESSION",
  "is_completed": false,
  "estimated_minutes": 60
}
```

Fetch the full item content (below) to get the schedule/guest/join details for rendering the item
card properly — same pattern as how you'd fetch full content for any other item type before
rendering more than a title.

**`GET /learning/courses/{course_id}/items/{item_id}`** — the full-detail endpoint you already call
when a student opens an item:

```json
{
  "id": "item-uuid",
  "title": "Live Q&A: Crisis Intervention Techniques",
  "item_type": "LIVE_SESSION",
  "is_completed": false,
  "estimated_minutes": 60,
  "live_session_scheduled_start_at": "2026-09-20T15:00:00Z",
  "live_session_duration_minutes": 60,
  "live_session_guest_name": "Dr. Amara Okafor",
  "live_session_guest_title": "Clinical Director, Crisis Response Network",
  "live_session_status": "SCHEDULED",
  "live_session_can_join": false,
  "live_session_recording_status": null,
  "live_session_recording_url": null
}
```

| Field | Notes |
|---|---|
| `live_session_can_join` | **The one field to gate your "Join" button on.** `true` only while the join window is open (opens 10 minutes before `live_session_scheduled_start_at`, closes 30 minutes after the scheduled end). Don't compute this window yourself client-side — the backend is the source of truth, and it also drives whether the join endpoint (§3) will actually succeed. |
| All other `live_session_*` fields | Same meaning as the `live_session` object on the course-detail endpoint above — just flattened with a `live_session_` prefix here, matching how `video_url`/`document_url`/`link_url` are flattened on this same endpoint. |

> Note the shape difference: the **course-detail** endpoint nests fields under a `live_session`
> object; the **learning item-content** endpoint uses flat `live_session_*` fields. Same underlying
> data, two response shapes, matching the existing convention for every other item type on these two
> endpoints.

---

## 2. Live sessions across all your courses (dashboard/upcoming view)

For an "Upcoming Live Sessions" widget or a dedicated schedule page, you don't need to loop over
every enrolled course and fetch its curriculum individually — there's a single cross-course
endpoint.

**`GET /learning/live-sessions`**

**Query parameters (all optional):**

| Param | Type | Notes |
|---|---|---|
| `course_id` | UUID | Narrow to a single course. Omit to get sessions across every enrolled course. |
| `start_date` | ISO 8601 datetime | Only sessions with `scheduled_start_at >= start_date`. |
| `end_date` | ISO 8601 datetime | Only sessions with `scheduled_start_at <= end_date`. |
| `page` / `page_size` | int | Standard pagination (default `page=1`, `page_size=20`, max `page_size=100`). |

Pass `start_date` and `end_date` together to scope to a range (e.g. "this week"); pass either alone
for an open-ended bound; omit both for every live session across every enrolled course, past and
future.

**Response (`200`, paginated):**

```json
{
  "success": true,
  "message": "OK",
  "data": [
    {
      "item_id": "item-uuid",
      "title": "Live Q&A: Crisis Intervention Techniques",
      "course_id": "course-uuid",
      "course_title": "Trauma-Informed Care",
      "course_slug": "trauma-informed-care",
      "section_id": "section-uuid",
      "section_title": "Module 3: Crisis Intervention",
      "scheduled_start_at": "2026-09-20T15:00:00Z",
      "scheduled_end_at": "2026-09-20T16:00:00Z",
      "duration_minutes": 60,
      "guest_name": "Dr. Amara Okafor",
      "guest_title": "Clinical Director, Crisis Response Network",
      "status": "SCHEDULED",
      "can_join": false,
      "is_completed": false,
      "recording_status": null,
      "recording_playback_url": null
    }
  ],
  "meta": {
    "page": 1,
    "page_size": 20,
    "total_items": 1,
    "total_pages": 1,
    "has_next": false,
    "has_previous": false
  }
}
```

Results are always sorted by `scheduled_start_at` ascending (soonest first) — including past
sessions when your date range covers them, so a "this week" query naturally lists earlier-in-the-week
sessions before later ones.

| Field | Notes |
|---|---|
| `course_slug` | Use this to build the item's deep link — `/courses/{course_slug}/live-session/{item_id}` — same URL the notification emails use (§7). |
| `section_id` / `section_title` | Which module/section this session belongs to, in case you want to group the dashboard by course+section. |
| `can_join` | Same join-window rule as `live_session_can_join` elsewhere — `true` only while the session is actually joinable right now. |
| Every other field | Same meaning as the equivalent `live_session*` field described in §1. |

**Suggested UI treatment:** a "Your upcoming live sessions" list on the student dashboard/home,
each row showing course title, session title, date/time, guest (if any), and a "Join" button that's
only enabled when `can_join: true` — clicking it follows the same join flow as §3.

---

## 3. Joining the call

**The call itself is not embedded in the app.** Clicking "Join" takes the student to daily.co's own
hosted room page (on their `socialworknigeria.daily.co` subdomain), where daily.co's own call UI
runs — full grid/speaker view, mute/camera controls, screen share, chat, participant list. Your
frontend never renders any video/WebRTC UI itself; its only job is to fetch the join URL and send the
browser there.

**`POST /courses/items/{item_id}/live-session/join`**

Call this the moment the student clicks "Join" — don't pre-fetch and hold onto the URL, since the
auth token baked into it is minted fresh per click and expires.

**Request:** no body.

**Response (`200`):**

```json
{
  "success": true,
  "message": "Join credentials generated successfully",
  "data": {
    "join_url": "https://socialworknigeria.daily.co/session-abc123-f9e8d7c6?t=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "is_owner": false,
    "expires_at": "2026-09-20T16:30:00Z"
  }
}
```

| Field | Notes |
|---|---|
| `join_url` | The full daily.co room URL with a per-user auth token already baked in (`?t=...`). Send the browser here directly — nothing else to construct. Not reusable after `expires_at`, and not valid for any other user or session. |
| `is_owner` | `true` if the caller is the course's instructor/admin (grants moderator-style controls on daily.co's page — e.g. can start/stop recording, remove participants); `false` for a regular student. Informational only — you don't need to do anything with it, daily.co's own UI already adapts based on the token. |
| `expires_at` | When the link stops working (the join window has closed). |

**Integration — this is the entire client-side implementation:**

```js
const { data } = await api.post(`/courses/items/${itemId}/live-session/join`);
window.location.assign(data.join_url); // or window.open(data.join_url, '_blank')
```

Open in a new tab if you want the student to keep your app open behind it, or navigate the current
tab away entirely — either is fine, there's no in-app state to preserve during the call.

### Error responses

| Status | When |
|---|---|
| `403` | You're not enrolled in this course (and not the instructor/admin). |
| `400` | `"This live session hasn't opened for joining yet"` — before the window opens; `"This live session has ended"` — after the window closes. Use `live_session_can_join` from the item-content endpoint to avoid hitting this in normal use; still handle it defensively (e.g. someone leaves the tab open past the window). |
| `404` | Item doesn't exist, or isn't a live session. |

**Suggested UI treatment:** show a countdown ("Starts in 2h 15m") when `live_session_can_join` is
`false` and the session is still `SCHEDULED`, and swap to an enabled "Join Now" button the moment
it flips `true`. Poll or re-fetch the item content periodically if the student has the page open
waiting for the window to open (there's no push notification for this — the reminder email is the
primary "it's starting soon" signal).

---

## 4. Rendering by status

| `live_session.status` | Suggested treatment |
|---|---|
| `SCHEDULED` (with `live_session_can_join: false`) | Show date/time, guest info, and a countdown ("Starts in ..."). |
| `SCHEDULED` (with `live_session_can_join: true`) | The join window is open — show a prominent enabled "Join Now" button. This is the state a session is in for its entire actual call duration; there's no separate `LIVE` status transition to key off today (see note above), so `live_session_can_join` is what tells you the call is happening now. |
| `ENDED` | Hide "Join". If `recording_status: "READY"`, show a video player using `recording_playback_url` (or `live_session_recording_url`) — treat it exactly like a `VIDEO` item's playback. If `recording_status` is `null`/`PENDING`/`PROCESSING`, show "Recording processing, check back soon." If `FAILED`, omit the recording section entirely (no error needed — just nothing to play). |
| `CANCELLED` | Reserved for future use — not currently reachable via any endpoint. If you ever see it, treat it like `ENDED` with no recording: hide "Join" and any countdown. |

---

## 5. Completion tracking

**`POST /learning/courses/{course_id}/items/{item_id}/complete`** — works for `LIVE_SESSION` items
exactly like it does for `VIDEO`/`DOCUMENT`/`LINKS` (unchanged endpoint, no new behavior). There's no
automatic "attended" detection — call this the same way you'd mark any non-assessment item done,
whatever trigger your UI already uses (e.g. when the student leaves the call, or when they watch the
recording, or via an explicit "Mark as complete" action).

---

## 6. Emails and calendar invites (automatic — no frontend work needed)

You don't need to build any of this — it's sent automatically by the backend. Documented here so you
know what the student already receives and don't duplicate it:

- **When a session is scheduled:** every enrolled student gets an email with the date/time, guest
  info (if any), a "Join Live Session" button (linking to a frontend URL — see §6), "Add to Google
  Calendar" / "Add to Outlook" one-click links, and a `.ics` file attached (works with Apple Calendar
  and any other calendar app).
- **When a session is rescheduled:** every enrolled student gets an email showing the old time
  struck through and the new time, plus a fresh calendar invite.
- **Before the session starts:** every enrolled student gets a reminder email (default: 60 minutes
  before `scheduled_start_at`) with a prominent "Join Now" button.

None of this requires an API call from your frontend — it fires server-side when the instructor
creates/edits the live session item.

---

## 7. Frontend page for the email's "Join" link

The scheduled/reminder emails link to:

```
{FRONTEND_URL}/courses/{course_slug}/live-session/{item_id}
```

**You need to build this page — but it's a redirector, not a call screen.** It should:

1. If the visitor isn't logged in, prompt login/signup first (standard auth-gate pattern, same as
   any other deep link into course content).
2. Once authenticated, call `POST /courses/items/{item_id}/live-session/join` and immediately send
   the browser to the returned `join_url` (see §3) — e.g. `window.location.assign(join_url)`. The
   student ends up on daily.co's own page for the actual call; this page's only job is the
   auth-check-then-redirect hop.
3. If the join call 403s (not enrolled), show a normal "you don't have access to this course" state
   with a link to the course's public page.
4. If the join call 400s (outside the join window), show the scheduled time and a "come back closer
   to start time" message instead of redirecting.

Same "Join Now" button inside the app itself (e.g. from the curriculum item card) can skip the
intermediate page and just call the join endpoint + redirect directly, the same way — the frontend
page above only exists to handle the case of someone arriving cold from an email link.

---

## 8. Endpoint reference summary

| Endpoint | What's new |
|---|---|
| `GET /courses/{slug}`, `/manage/{id}` (and similar course-detail endpoints) | A `LIVE_SESSION` item includes a `live_session` object. |
| `GET /learning/courses/{course_id}/items/{item_id}` | A `LIVE_SESSION` item includes flat `live_session_*` fields, including the join-window flag `live_session_can_join`. |
| `GET /learning/live-sessions` | **New.** Cross-course list of live sessions across every enrolled course, with optional `course_id`/`start_date`/`end_date` filters and pagination. |
| `POST /courses/items/{item_id}/live-session/join` | **New.** Returns a `join_url` (daily.co's own hosted room, auth token baked in) for the current user — redirect the browser there, no in-app call UI to build. |
| `POST /learning/courses/{course_id}/items/{item_id}/complete` | Unchanged — now also valid for `LIVE_SESSION` items. |

---

## 9. Error responses you should handle

| Status | When |
|---|---|
| `400` | Joining outside the session's join window (see §3). |
| `403` | Joining a live session for a course you're not enrolled in. Also unchanged pre-existing cases: not enrolled, section locked, scheduled course outside its access window. |
| `404` | Item/course id doesn't exist, or the item isn't a live session. |

---

## 10. Frontend implementation checklist

- [ ] Curriculum renderer: add `"LIVE_SESSION"` as a fifth item type alongside `VIDEO`/`DOCUMENT`/
  `ASSESSMENT`/`LINKS` — icon (e.g. a calendar/camera glyph), title, scheduled date/time (localized),
  and guest byline when `guest_name` is set.
- [ ] Item detail view: render date/time, guest info, and a "Join"/countdown control driven by
  `live_session_can_join` and `live_session_status`. "Join" calls the join endpoint and redirects to
  `join_url` — no in-app video component needed.
- [ ] Build the `/courses/{slug}/live-session/{item_id}` deep-link page that the scheduled/reminder
  emails point to (auth-gate → call the join endpoint → redirect to `join_url`). This is a thin
  redirector, not a call screen — the actual call UI is entirely daily.co's own hosted page.
- [ ] Do **not** add `@daily-co/daily-js` or any embedded call UI — the call intentionally happens on
  daily.co's own subdomain (`socialworknigeria.daily.co`), outside the app.
- [ ] After `status: "ENDED"` with `recording_status: "READY"`, render `recording_playback_url` in
  your existing video player component — no new player needed.
- [ ] Double-check any place you hardcode/switch on `item_type` values (e.g. an enum/union type in
  your frontend code) to make sure `"LIVE_SESSION"` doesn't silently fall through to a default/
  unknown state.
- [ ] No work needed for emails/calendar invites — fully automatic server-side (see §6).
- [ ] Build an "Upcoming Live Sessions" dashboard/schedule widget backed by `GET
  /learning/live-sessions` (§2) — no need to fetch every course's curriculum separately.
