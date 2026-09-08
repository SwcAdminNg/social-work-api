# Dashboard — Student API Reference

Everything the student dashboard homepage needs: one aggregated "overview" call for what's above the
fold, plus the existing full/paginated endpoint each section already had for its own "view all"
screen. Nothing here duplicates data storage — the overview endpoint is a read-only composition of
services that already exist elsewhere in the API (learning, certificates, payments, community,
support, notifications).

Base URL prefix for the new endpoint: `/users/me/dashboard`.

> ℹ️ Global response quirk: the API strips null/absent fields from JSON output. If a field isn't in
> the response, treat it as `null`/unset — don't treat its absence as an error.

---

## Conventions

- **Auth**: everything below requires `Authorization: Bearer <token>`.
- **Response envelope**: `ApiResponse<T>` for single items, `PaginatedResponse<T>` for list
  endpoints.

---

## 1. The one call for the homepage

```
GET /users/me/dashboard/overview?limit=5
```

`limit` (optional, default `5`) caps how many items each list section returns — it's meant for
compact "top N" widgets, not full lists. Every section also has its own full/paginated endpoint for
a "view all" click-through (see §3).

```json
{
  "success": true,
  "message": "Dashboard overview retrieved successfully",
  "data": {
    "stats": {
      "total_courses_enrolled": 6,
      "quizzes_attempted": 14,
      "completion_rate": 62.5,
      "total_reviews": 2,
      "in_process_courses": 3,
      "completed_courses": 2,
      "not_started_courses": 1,
      "bookmarked_courses": 4
    },
    "continue_learning": [
      {
        "course_id": "4f421cec-....",
        "title": "Intro to Social Work",
        "slug": "intro-to-social-work",
        "thumbnail_url": "https://pub-....r2.dev/....png",
        "progress_percent": 62,
        "last_accessed_at": "2026-09-07T18:04:00Z"
      }
    ],
    "upcoming_live_sessions": [
      {
        "item_id": "9c31....",
        "title": "Live Q&A: Case Studies",
        "course_id": "4f421cec-....",
        "course_title": "Intro to Social Work",
        "course_slug": "intro-to-social-work",
        "section_id": "e5f6....",
        "section_title": "Module 3",
        "scheduled_start_at": "2026-09-10T15:00:00Z",
        "scheduled_end_at": "2026-09-10T16:00:00Z",
        "duration_minutes": 60,
        "guest_name": null,
        "guest_title": null,
        "status": "SCHEDULED",
        "can_join": false,
        "is_completed": false,
        "recording_status": null
      }
    ],
    "recent_certificates": [
      {
        "id": "b6e2a1f0-....",
        "course_id": "7a2c....",
        "course_title": "Foundations of Casework",
        "recipient_name": "Ada Obi",
        "certificate_number": "SW-2026-9F3A2B10",
        "verification_code": "xY_9f2a...",
        "issued_at": "2026-08-20T10:00:00Z",
        "pdf_url": "https://....pdf",
        "verify_url": "https://.../certificates/verify/xY_9f2a..."
      }
    ],
    "recent_activity": [
      { "id": "...", "user_id": "...", "activity_type": "QUIZ_COMPLETED", "metadata_json": { "course_id": "...", "score": 85 }, "created_at": "2026-09-07T20:10:00Z" }
    ],
    "unread_notifications_count": 4,
    "unread_community_messages_count": 27,
    "open_support_tickets_count": 1,
    "cart_item_count": 2,
    "subscription": {
      "id": "...",
      "plan_id": "...",
      "start_date": "2026-08-01T00:00:00Z",
      "end_date": "2026-09-01T00:00:00Z",
      "is_active": true,
      "auto_renew": true,
      "pending_plan_id": null,
      "plan": { "id": "...", "name": "Pro Monthly", "price": 15000, "duration_days": 30, "...": "..." }
    }
  }
}
```

`subscription` is `null` if the student has no active subscription — same shape and meaning as
`GET /payments/subscriptions/current` (§3).

### Section notes

- **`continue_learning`** — the student's most-recently-accessed enrolled courses, **already
  excluding fully-completed ones** (those belong in the certificates/completed section instead). If
  it comes back empty for a student with enrollments, they just haven't started any of them yet —
  pair this widget with a fallback state pointing at `stats.not_started_courses`.
- **`upcoming_live_sessions`** — filtered to `scheduled_start_at >= now`, soonest first. `can_join`
  becomes `true` only inside the actual join window (10 min before start through 30 min after the
  scheduled end) — use it to decide whether the "Join" button on a card is active or just shows the
  scheduled time.
- **`recent_certificates`** — most recently issued first.
- **`recent_activity`** — see [`DEVELOPER_ONBOARDING.md`](../phase_1/DEVELOPER_ONBOARDING.md) or the
  `ActivityTypeEnum` values directly for the full set of `activity_type`s
  (`COURSE_ENROLLED`, `QUIZ_COMPLETED`, `QUIZ_GROUP_COMPLETED`, `ESSAY_SUBMITTED`, `ESSAY_GRADED`,
  `REVIEW_CREATED`, `REVIEW_EDITED`, `REVIEW_DELETED`, `PAYMENT_SUCCESSFUL`) — render a per-type
  icon/message from `activity_type` + whatever's useful in `metadata_json`.
- **`unread_community_messages_count`** counts unread messages across *every* community the student
  belongs to (including the platform-wide General/Help rooms) — same figure as
  `GET /community/unread-count`. It can look large for a student who's never opened chat; that's
  expected, not a bug (see the Community docs).
- **`open_support_tickets_count`** counts tickets in `OPEN` or `IN_PROGRESS` only — resolved/closed
  tickets don't count.

---

## 2. Recommended layout

A sensible "meant to be a dashboard" homepage from this one payload:

1. **Header stat row** — `stats.completion_rate`, `stats.in_process_courses`,
   `stats.completed_courses`, `stats.total_courses_enrolled` as compact KPI tiles.
2. **"Continue learning" rail** — cards from `continue_learning`, each linking to
   `/learn/{course_id}` with a progress bar from `progress_percent`.
3. **"Upcoming live sessions" widget** — cards from `upcoming_live_sessions`, each linking to
   `/courses/{course_slug}/live-session/{item_id}`; show a "Join now" state when `can_join` is true.
4. **Notifications / activity feed** — `recent_activity`, optionally interleaved with a live feed
   from the Notifications WebSocket (see `NOTIFICATIONS_STUDENT_API.md`) for anything that happens
   while the dashboard is open.
5. **Badges in the top nav** — `unread_notifications_count` (bell icon),
   `unread_community_messages_count` (chat icon), `cart_item_count` (cart icon),
   `open_support_tickets_count` (help icon) — all four are cheap enough to also refresh via their own
   endpoints on an interval if you don't want to re-fetch the whole overview just for a badge.
6. **Subscription/billing card** — render `subscription`, or a "You're on the free tier — upgrade"
   CTA when it's `null`.
7. **Recent certificates strip** — `recent_certificates`, each linking to
   `/dashboard/certificates/{course_id}`, with a "view all" linking to the full certificates list.

---

## 3. Drill-down / "view all" endpoints (already exist — reuse, don't duplicate)

Every overview section has a full paginated endpoint of its own for when the student clicks
"view all" — call these instead of re-fetching `/overview` with a bigger `limit`:

| Section | Endpoint | Notes |
|---|---|---|
| Enrolled courses / continue learning | `GET /learning/courses` | Full `EnrolledCourseDTO` list, same sort order (most recently accessed first). |
| Upcoming / all live sessions | `GET /learning/live-sessions?start_date=...&end_date=...&course_id=...` | Drop `start_date` to include past sessions too; filter by course with `course_id`. |
| Certificates | `GET /certificates/mine` | Full certificate list. |
| Activity | `GET /users/me/dashboard/activity` | Already existed before this feature — unchanged. |
| Notifications | `GET /notifications` (+ `WS /notifications/ws`) | See `NOTIFICATIONS_STUDENT_API.md`. |
| Community unread / rooms | `GET /community`, `GET /community/unread-count` | See `COMMUNITY_STUDENT_API.md`. |
| Support tickets | `GET /support/tickets/mine` | See `HELP_SUPPORT_USER_API.md`; filter client-side by `status` for an "open" view, or trust `open_support_tickets_count` for the badge. |
| Cart | `GET /cart` | Returns full `CartReadDTO` (`items`, `item_count`, `subtotal_amount`). |
| Subscription / billing | `GET /payments/subscriptions/current`, `GET /payments/transactions/me` | Same `CurrentSubscriptionResponse` shape as the overview's `subscription` field. |
| Assessment performance (optional, not in overview) | `GET /learning/assessments/stats`, `GET /learning/assessments/me` | Worth a dedicated "My Assessments" widget/page if you want more than the overview's `stats.quizzes_attempted`. |

---

## 4. Endpoint reference (new in this feature)

| Endpoint | What it does |
|---|---|
| `GET /users/me/dashboard/overview?limit=5` | Everything above the fold in one call — see §1. |
| `GET /users/me/dashboard/stats` | Unchanged, pre-existing. Also embedded as `overview.stats`. |
| `GET /users/me/dashboard/activity` | Unchanged, pre-existing. Also embedded (capped at `limit`) as `overview.recent_activity`. |

---

## 5. Frontend implementation checklist

- [ ] Dashboard page fires **one** request on load: `GET /users/me/dashboard/overview` — don't
      re-implement per-section fetching for the initial paint, it already costs one DB round-trip
      per section server-side even though it's one HTTP call.
- [ ] Wire the four nav badges (notifications, community, cart, support) from the overview payload
      on load, then keep notifications/community live via their WebSockets afterward (see their own
      docs) rather than polling `/overview` again.
- [ ] Each dashboard widget's "view all" / "see more" link routes to the corresponding full endpoint
      in §3, not a bigger `limit` on `/overview`.
- [ ] Empty states: handle `continue_learning: []` (new/no-progress student — show a "browse
      courses" CTA), `upcoming_live_sessions: []` (no upcoming sessions), `subscription: null` (no
      active plan — show an upgrade CTA), `recent_certificates: []` (nothing earned yet).
- [ ] `can_join` on a live-session card should drive whether the CTA is "Join now" (active, deep-link
      to the live-session page which calls the join-token endpoint) vs. just showing the scheduled
      time.
- [ ] Treat `limit` as a display cap, not a "how many exist" signal — use the relevant `stats.*`
      field or the drill-down endpoint's `meta.total_items` to show real counts (e.g. "3 courses in
      progress" even if only `limit=5` cards are shown).
