# Cart &amp; Coupons — Admin API Reference

This document covers the **management** side of the coupon system: creating discount codes and
configuring their rules. There is no admin side to the cart itself — a cart is just a list of
courses a student has queued up to buy, nothing an admin creates or moderates — so this doc is
coupon-only. It's the companion to
[`CART_COUPON_STUDENT_API.md`](./CART_COUPON_STUDENT_API.md), which covers the cart (add/remove/
checkout) and the student-facing coupon preview endpoint.

Base URL prefix for everything below: `/coupons`.

> ℹ️ Global response quirk: the API strips null/absent fields from JSON output. If a field isn't
> in the response, treat it as `null`/unset — don't treat its absence as an error.

---

## Conventions

- **Auth**: every endpoint in this document requires `Authorization: Bearer <token>` for a user
  who is `ADMIN` (`get_current_admin_user`). There is no instructor-level coupon access.
- **Response envelope**: `ApiResponse<T>` — `{ "success": true, "message": "...", "data": {...} }`.
  `GET /coupons` (list) returns `PaginatedResponse<T>` with a `meta` block.
- **Null stripping**: absent/null fields are stripped from JSON responses — treat a missing field
  as `null`.
- **Money**: all amounts are plain Naira floats (e.g. `5000.00`), no kobo conversion — same
  convention as the rest of the payments API.
- **`code`** is always normalized to uppercase server-side, on both create and update — send it in
  whatever case is convenient, the API will store/compare it uppercased.

---

## 1. The mental model

A `Coupon` is a single discount code with a set of rules that all must pass for it to apply.
Redemption (the counters below) only increments when a payment actually **succeeds** — a coupon
entered but abandoned at checkout never consumes a redemption slot.

| Field | Type | Purpose |
|---|---|---|
| `code` | string | What the student types in. Unique, case-insensitive. |
| `discount_type` | `PERCENTAGE` \| `FIXED_AMOUNT` | The discount shape. |
| `discount_value` | number | `%` (0–100) if `PERCENTAGE`, or a flat Naira amount if `FIXED_AMOUNT`. |
| `max_discount_amount` | number, nullable | Caps a `PERCENTAGE` discount in Naira — e.g. "20% off, up to ₦5,000". Ignored for `FIXED_AMOUNT` (already a hard cap). |
| `min_order_amount` | number, nullable | Cart/order subtotal must be at least this much to use the coupon. |
| `valid_from` / `valid_until` | datetime, nullable | Time-box a promo. Omit either side to leave that end open. |
| `max_redemptions` | int, nullable | Global cap across all users — e.g. "first 100 uses." |
| `max_redemptions_per_user` | int, default `1` | Per-user cap — the standard "one use per customer" guard. |
| `times_redeemed` | int, **read-only** | Running count of successful redemptions. Only settable by the system. |
| `applicable_course_ids` | array of course UUIDs, nullable | Scope the discount to specific courses. |
| `applicable_category` | one of the course category enum values, nullable | Scope the discount to a whole category instead of naming courses one by one. |
| `new_users_only` | bool, default `false` | Only usable by a user with no prior successful purchase — a first-purchase acquisition coupon. |
| `is_active` | bool, default `true` | Kill-switch — set `false` to disable without deleting (keeps redemption history intact). |

**Scoping logic** (`applicable_course_ids`/`applicable_category`): if both are null, the coupon
applies to everything. If either is set, a course qualifies by matching *either* condition. In a
cart with a mix of qualifying and non-qualifying courses, the discount is computed only against
the qualifying items' subtotal — the order isn't rejected wholesale. See the student doc's
"Discount computation" section for the exact math with a worked example.

---

## 2. Create a coupon

```
POST /coupons
Authorization: Bearer <admin_token>
```

```json
{
  "code": "WELCOME20",
  "description": "20% off, first purchase only, capped at N5,000",
  "discount_type": "PERCENTAGE",
  "discount_value": 20,
  "max_discount_amount": 5000,
  "min_order_amount": null,
  "valid_from": null,
  "valid_until": "2026-12-31T23:59:59Z",
  "max_redemptions": null,
  "max_redemptions_per_user": 1,
  "applicable_course_ids": null,
  "applicable_category": null,
  "new_users_only": true,
  "is_active": true
}
```

Only `code`, `discount_type`, and `discount_value` are required — everything else has a sensible
default (see the table above) or is nullable/optional.

**Response** — `201 Created`, `ApiResponse<CouponReadDTO>`:

```json
{
  "success": true,
  "message": "Coupon created successfully",
  "data": {
    "id": "d4e5f6a7-....",
    "code": "WELCOME20",
    "description": "20% off, first purchase only, capped at N5,000",
    "discount_type": "PERCENTAGE",
    "discount_value": 20.0,
    "max_discount_amount": 5000.0,
    "min_order_amount": null,
    "valid_from": null,
    "valid_until": "2026-12-31T23:59:59Z",
    "max_redemptions": null,
    "max_redemptions_per_user": 1,
    "times_redeemed": 0,
    "applicable_course_ids": null,
    "applicable_category": null,
    "new_users_only": true,
    "is_active": true,
    "created_at": "2026-09-03T09:00:00Z"
  }
}
```

**Errors**: `409 Conflict` — `"A coupon with this code already exists"`. `422` on validation
failures, e.g. a `PERCENTAGE` `discount_value` over 100.

---

## 3. List coupons

```
GET /coupons?page=1&page_size=20
Authorization: Bearer <admin_token>
```

Returns every coupon — active or not — newest first. `PaginatedResponse<CouponReadDTO>`, same
shape as §2's `data` object but as a list, plus the standard `meta` block (`page`, `page_size`,
`total_items`, `total_pages`, `has_next`, `has_previous`).

There's no server-side filter (by `is_active`, expiry, etc.) — filter client-side if you need a
"active only" or "expired" view.

---

## 4. Get / update / delete a coupon

```
GET    /coupons/{coupon_id}
PATCH  /coupons/{coupon_id}
DELETE /coupons/{coupon_id}
Authorization: Bearer <admin_token>
```

- `GET` returns the same `CouponReadDTO` shape as create.
- `PATCH` accepts a partial body — send only the fields you want to change. Same field set as
  create, all optional. Changing `code` re-checks uniqueness (`409` if it collides with another
  coupon). You **cannot** set `times_redeemed` directly — it's not part of the update DTO; it only
  moves via actual redemptions.
- `DELETE` is a **soft delete** — the coupon (and its redemption history) is preserved for
  records/reporting, it just stops being usable (a soft-deleted coupon can't be found by code, so
  it behaves as if it doesn't exist to students). All three return `404` if the id doesn't exist.

**The fast way to pause a promo without losing its history**: `PATCH` with `{"is_active": false}`
instead of deleting — this is reversible and keeps `times_redeemed` visible, whereas delete is
meant for coupons you're permanently done with.

---

## 5. Reading redemption activity

There's currently no dedicated "list redemptions for this coupon" endpoint — `times_redeemed` on
the coupon itself (§2–4) is the running total. Each individual redemption is recorded internally
(coupon, user, transaction, discount amount) for audit purposes but isn't yet exposed via the API;
flag it if your admin dashboard needs a per-redemption breakdown and it can be added as a follow-up
endpoint (e.g. `GET /coupons/{coupon_id}/redemptions`).

---

## 6. Designing rules for common promo scenarios

A quick cheat-sheet for translating a marketing ask into the fields above:

| Scenario | Fields to set |
|---|---|
| "20% off, no cap" | `discount_type: PERCENTAGE`, `discount_value: 20` |
| "20% off, capped at ₦5,000" | add `max_discount_amount: 5000` |
| "₦2,000 off any order over ₦10,000" | `discount_type: FIXED_AMOUNT`, `discount_value: 2000`, `min_order_amount: 10000` |
| "First 100 people only" | `max_redemptions: 100` |
| "One use per customer" (default) | leave `max_redemptions_per_user` at `1` |
| "Unlimited uses per customer" (rare, e.g. a staff code) | set `max_redemptions_per_user` to something very large |
| "First-time buyers only" | `new_users_only: true` |
| "20% off this one course" | `applicable_course_ids: ["<course-id>"]` |
| "20% off everything in Development" | `applicable_category: "DEVELOPMENT"` |
| "Flash sale, this weekend only" | `valid_from`/`valid_until` bracketing the window |
| "Kill a promo immediately" | `PATCH { "is_active": false }` |
