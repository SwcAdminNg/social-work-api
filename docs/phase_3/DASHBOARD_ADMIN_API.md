# Dashboard — Admin API Reference

Everything the admin dashboard homepage needs: one aggregated "overview" call for platform-wide
stats (users, revenue, courses, support queue, reviews, contact messages, coupons, certificates),
plus references to the existing admin list endpoints each stat drills down into. This is the
admin-side counterpart to [`DASHBOARD_STUDENT_API.md`](./DASHBOARD_STUDENT_API.md) — same idea, but
every number here is platform-wide, not scoped to one user.

Base URL for the new endpoint: `/admin/dashboard/overview`.

> ℹ️ Global response quirk: the API strips null/absent fields from JSON output. If a field isn't in
> the response, treat it as `null`/unset — don't treat its absence as an error.

---

## Conventions

- **Auth**: `Authorization: Bearer <token>` for a user whose `user_type` is `ADMIN`. `403` for
  anyone else (including instructors/Support Desk staff).
- **Response envelope**: `ApiResponse<T>`.
- **Money fields** (`revenue.*`) are plain numbers in Naira, already tax-inclusive (same `amount`
  semantics as everywhere else in the payments API) — **`SUCCESS` transactions only**, never
  pending/failed attempts.

---

## 1. The one call for the homepage

```
GET /admin/dashboard/overview?limit=5
```

`limit` (optional, default `5`) caps `top_enrolled_courses`, `recent_signups`, and
`recent_transactions`. Every stat block is a platform-wide aggregate (not affected by `limit`).

```json
{
  "success": true,
  "message": "Admin dashboard overview retrieved successfully",
  "data": {
    "users": {
      "total_users": 1842,
      "students": 1790,
      "instructors": 41,
      "admins": 11,
      "suspended": 3,
      "new_last_7_days": 26,
      "new_last_30_days": 118
    },
    "revenue": {
      "total_all_time": 8452300.0,
      "last_30_days": 612400.0,
      "last_7_days": 148200.0,
      "active_subscriptions": 312
    },
    "courses": { "total": 64, "published": 58, "draft": 6 },
    "top_enrolled_courses": [
      {
        "course_id": "9f690f97-....",
        "title": "Ethics in Social Work",
        "slug": "ethics-in-social-work",
        "thumbnail_url": "https://....webp",
        "enrollment_count": 214
      }
    ],
    "support": { "open": 12, "in_progress": 5, "resolved": 340, "closed": 88, "unassigned_open": 7 },
    "reviews": { "platform_average_rating": 4.3, "total_reviews": 512, "pending_reply": 19 },
    "contact_messages": { "total": 203, "recent_7_days": 6 },
    "active_coupons": 4,
    "certificates_issued_total": 926,
    "certificates_issued_last_30_days": 71,
    "recent_signups": [
      { "id": "...", "first_name": "Ada", "last_name": "Obi", "email": "ada@example.com", "user_type": "USER", "created_at": "2026-09-07T20:10:00Z" }
    ],
    "recent_transactions": [
      { "id": "...", "reference": "TXN_9F3A2B10....", "amount": 15000.0, "status": "SUCCESS", "transaction_type": "COURSE_PURCHASE", "user_id": "...", "user_name": "Femi Adebayo", "created_at": "2026-09-08T09:01:00Z" }
    ]
  }
}
```

### Section notes

- **`users.students`** maps to `user_type == "USER"` (the platform's term for a regular
  student/learner account — `USER`/`INSTRUCTOR`/`ADMIN` are the only three types).
- **`revenue`** counts `SUCCESS` transactions only, so a spike in failed/abandoned checkouts never
  inflates it — pair with the transactions list (§3) if you want failure-rate visibility, which
  isn't in this overview.
- **`top_enrolled_courses`** is published courses only, ranked by total (not just active) enrollment
  count, most-enrolled first.
- **`support.unassigned_open`** is the subset of `open + in_progress` with no `assigned_admin_id` —
  this is the number worth a red badge; the full `open`/`in_progress` split is more of an at-a-glance
  queue-health figure.
- **`reviews.pending_reply`** counts non-hidden reviews with no `reply_text` yet, regardless of
  rating — a queue of reviews an instructor/admin hasn't responded to.
- **`contact_messages.recent_7_days`** is a recency count, **not an unread count** — the contact-us
  message model has no read/unread state, so "recent" is the closest honest proxy for "may need a
  look." Don't label it "unread" in the UI.
- **`active_coupons`** counts coupons that are `is_active` and not past their `valid_until` (coupons
  with no `valid_until` never expire on their own).
- **`recent_signups`**/**`recent_transactions`** are both newest-first, meant for a compact
  "what just happened" feed — not paginated lists.

---

## 2. Recommended layout

1. **KPI tile row** — `users.total_users`, `revenue.total_all_time` (or `last_30_days` if you want a
   "this month" framing), `courses.published`, `support.unassigned_open` (as an attention-grabbing
   tile, e.g. red when > 0).
2. **Revenue card** — `revenue.last_7_days` vs `last_30_days` as a small trend indicator, plus
   `active_subscriptions` as a secondary figure.
3. **"Needs attention" panel** — the numbers that represent admin work queued up:
   `support.unassigned_open`, `reviews.pending_reply`, `contact_messages.recent_7_days` — each
   linking to its respective queue (see §3).
4. **Top courses widget** — `top_enrolled_courses` as a short ranked list, each linking to
   `/dashboard/course-management/{course_id}`.
5. **Recent activity feed** — interleave `recent_signups` (→ `/dashboard/user-management/{id}`) and
   `recent_transactions` (→ `/dashboard/payments`), or show them as two side-by-side compact lists.
6. **Live notifications bell** — this overview is a point-in-time snapshot; pair it with the
   Notifications WebSocket (`NOTIFICATIONS_ADMIN_API.md`) for anything that happens while the
   dashboard is open (new tickets, new signups, new payments all push live there too).
7. **Secondary stats row** — `certificates_issued_total` / `_last_30_days`, `active_coupons`,
   `courses.draft` — lower-priority figures, fine as a footer row or a "platform health" expandable
   section rather than above the fold.

---

## 3. Drill-down / "view all" endpoints (admin-only, already exist — reuse, don't duplicate)

| Section | Endpoint | Notes |
|---|---|---|
| Users | `GET /users?user_type=...&search=...` | Full filterable user list. `POST /users/{id}/suspend` \| `/unsuspend` for the suspend count's source of truth. |
| Revenue / transactions | `GET /admin/payments` or `GET /payments/transactions` | Both exist (older/newer variants) — paginated transaction list with the requesting user joined in. |
| Tax report | `GET /payments/taxes?start_date=...&end_date=...` | VAT collected over a range — a separate, finance-specific view not folded into this overview. |
| Courses | `GET /courses/manage?...` | Full manageable course list (own courses for instructors, all for admins). |
| Support queue | `GET /support/tickets?status=...&assigned_admin_id=...&search=...` | Full filterable ticket queue — filter by `status=OPEN` and no `assigned_admin_id` to reproduce `unassigned_open` as a real list. |
| Reviews | `GET /courses/reviews/all` | Full review list across every course; `PATCH /courses/reviews/{id}/reply` to clear a "pending reply". |
| Contact messages | `GET /contact-us?search=...&start_date=...&end_date=...` | Full filterable list. |
| Coupons | `GET /coupons` | Full coupon list — filter `is_active`/`valid_until` client-side, or check each row's own fields. |
| Certificates | *(no dedicated admin "all certificates" list yet)* | Only a per-user list (`GET /certificates/mine`, as the user) and public verification (`GET /certificates/verify/{code}`) exist today — if you need a full admin certificates table, that'd be a new endpoint, not something to fake from the overview. |

---

## 4. Endpoint reference (new in this feature)

| Endpoint | What it does |
|---|---|
| `GET /admin/dashboard/overview?limit=5` | Everything above the fold in one call — see §1. Admin only. |

---

## 5. Frontend implementation checklist

- [ ] Dashboard page fires **one** request on load: `GET /admin/dashboard/overview`.
- [ ] "Needs attention" tiles (`support.unassigned_open`, `reviews.pending_reply`,
      `contact_messages.recent_7_days`) get a visually distinct treatment (badge/color) when > 0 —
      these are the numbers an admin dashboard exists to surface.
- [ ] Every stat block/list has a "view all" link routed to its §3 endpoint — don't paginate past
      `limit` on the overview itself.
- [ ] Wire the notification bell (`NOTIFICATIONS_ADMIN_API.md`) alongside this for live updates
      between page loads/refreshes — the overview itself is not live-updating.
- [ ] Empty/zero states: `top_enrolled_courses: []` (no published courses yet),
      `recent_transactions: []` / `recent_signups: []` (brand-new platform) should render sensible
      placeholders, not broken widgets.
- [ ] Treat `contact_messages.recent_7_days` as "recent," not "unread," in any label/tooltip — the
      backend has no read-state to back an unread claim (see §1 notes).
- [ ] If/when a full admin certificates list endpoint is added, wire its "view all" the same way as
      the other sections — until then, `certificates_issued_total`/`_last_30_days` are numbers only,
      with no drill-down target.
