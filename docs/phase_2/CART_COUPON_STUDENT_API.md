# Cart &amp; Coupons — Student API Reference

This document covers the **shopping** side of the payments system: adding courses to a cart,
previewing a coupon's discount, and checking out one or several courses at once. It's the
companion to [`CART_COUPON_ADMIN_API.md`](./CART_COUPON_ADMIN_API.md), which covers how admins
create and configure coupons.

It builds directly on the existing single-course payment flow — read
[`PAYMENT_RECEIPT_API.md`](../phase_1/PAYMENT_RECEIPT_API.md) first if you haven't already; cart
checkout reuses the exact same `initialize → redirect/pay → verify` cycle and the exact same
receipt-download endpoint, just for an order that can contain more than one course.

Base URL prefixes: `/cart` and `/coupons` for the endpoints below; `/payments` for the checkout
lifecycle they hand off to (verify, webhook, receipt download — all pre-existing and unchanged).

> ℹ️ Global response quirk: the API strips null/absent fields from JSON output. If a field isn't
> in the response, treat it as `null`/unset — don't treat its absence as an error.

---

## Conventions

- **Auth**: every endpoint below requires `Authorization: Bearer <token>`.
- **Response envelope**: `ApiResponse<T>` — `{ "success": true, "message": "...", "data": {...} }`.
  None of these endpoints are paginated (a cart realistically never has enough items to need it).
- **Money**: plain Naira floats (e.g. `25000.00`).
- A "cart" has no separate id or header object — it's simply the current user's set of cart items.
  There's nothing to create; adding your first item is enough.

---

## 1. The mental model

```
CartItem (user, course)  ──┐
                            │  POST /cart/checkout
CartItem (user, course)  ──┤  (reads the cart server-side,
                            │   you never send prices/ids yourself)
CartItem (user, course)  ──┘
                            │
                            ▼
                 Transaction (CART_PURCHASE)
                            │
                            ▼
                 TransactionItem × N  (one per course, price snapshotted at checkout)
```

- Adding a course to your cart doesn't reserve it or lock in its price — the price is only
  snapshotted at the moment you check out.
- A course drops out of eligibility (and checkout will reject it) if it stops being published,
  becomes free, or you already own it by the time you check out — even if it was fine when you
  added it. Refresh your cart (`GET /cart`) if checkout fails for this reason.
- Checkout empties the cart **only on successful payment** — an abandoned or failed payment leaves
  your cart exactly as it was, so you can just try again.
- Single-course checkout (`POST /payments/initialize`, unchanged from before) also now accepts a
  coupon — see §5. You don't have to use the cart just to apply a coupon to one course.

---

## 2. View your cart

```
GET /cart
Authorization: Bearer <token>
```

**Response** — `200 OK`, `ApiResponse<CartReadDTO>`:

```json
{
  "success": true,
  "message": "Cart retrieved successfully",
  "data": {
    "items": [
      {
        "course_id": "c9d8e7f6-....",
        "course_title": "Introduction to Social Work Practice",
        "course_slug": "introduction-to-social-work-practice",
        "course_thumbnail_url": "https://.../thumb.jpg",
        "price": 15000.0,
        "added_at": "2026-09-03T10:00:00Z"
      },
      {
        "course_id": "a1b2c3d4-....",
        "course_title": "Trauma-Informed Care",
        "course_slug": "trauma-informed-care",
        "course_thumbnail_url": "https://.../thumb2.jpg",
        "price": 10000.0,
        "added_at": "2026-09-03T10:02:00Z"
      }
    ],
    "item_count": 2,
    "subtotal_amount": 25000.0
  }
}
```

An empty cart returns `"items": [], "item_count": 0, "subtotal_amount": 0`, not an error.

---

## 3. Add / remove items

```
POST /cart/items
Authorization: Bearer <token>
```
```json
{ "course_id": "c9d8e7f6-...." }
```
Returns the updated cart (§2's shape) on success. **Errors**, all `400` unless noted:
- `404` — course doesn't exist (or isn't published).
- `"This course is free - no need to add it to a cart"` — free courses aren't purchasable, add via
  enrollment instead.
- `"You already have access to this course"` — you already own it (purchased, subscription, or an
  admin grant).
- `"This course is already in your cart"` — no duplicates.

```
DELETE /cart/items/{course_id}
Authorization: Bearer <token>
```
Removes one item. `404` — `"Item not found in cart"` if it wasn't there. Returns the updated cart.

```
DELETE /cart
Authorization: Bearer <token>
```
Empties the whole cart. `ApiResponse<None>`.

---

## 4. Checkout

```
POST /cart/checkout
Authorization: Bearer <token>
```
```json
{
  "coupon_code": "WELCOME20",
  "gateway": "PAYSTACK",
  "save_card": false
}
```
All three fields are optional — omit `coupon_code` to check out without a discount; `gateway`
defaults to `"PAYSTACK"` (the only gateway currently implemented); `save_card` defaults to `false`.

**Response** — `200 OK`, `ApiResponse<InitializePaymentResponse>` — **identical shape** to the
existing single-course `POST /payments/initialize` response:

```json
{
  "success": true,
  "message": "Checkout initialized",
  "data": {
    "authorization_url": "https://checkout.paystack.com/abc123xyz",
    "access_code": "abc123xyz",
    "reference": "TXN_A1B2C3D4E5F6A1B2C3D4"
  }
}
```

From here, the flow is **exactly the existing payment flow** — redirect the user to
`authorization_url`, then call `GET /payments/verify/{reference}` after they return (or just wait
for the webhook, which fires the same grant either way). On success:

- Access is granted for **every** course in the cart at the time of checkout, not just some.
- The cart is cleared.
- One receipt email + PDF is sent covering the whole order (all courses, one combined total) — see
  §6.
- If a coupon was used, it's marked redeemed at this point (not before) — see the admin doc for
  what that means for redemption caps.

**Errors**, all `400` unless noted:
- `"Your cart is empty"`.
- `"One or more items in your cart no longer exist - please refresh your cart"`.
- `"'<course>' is no longer available for purchase - please remove it from your cart"` — it
  became unpublished or free since you added it.
- `"You already have access to: <course>, <course> - please remove from your cart"` — you gained
  access to one or more cart items some other way (e.g. a subscription) since adding them.
- Any coupon rejection reason from §5's table, if `coupon_code` was supplied and fails validation.

---

## 5. Coupons

### Preview a discount

```
POST /coupons/validate
Authorization: Bearer <token>
```
```json
{ "code": "WELCOME20", "course_ids": null }
```
`course_ids` is optional — omit it (or pass `null`) to preview against your **current cart**;
pass an explicit list to preview against a specific set of courses instead (e.g. to show the
discount on a single course's checkout/detail page before it's ever added to a cart).

**Response** — `200 OK`, `ApiResponse<CouponValidateResponse>`:

```json
{
  "success": true,
  "message": "Coupon applied",
  "data": {
    "valid": true,
    "code": "WELCOME20",
    "subtotal_amount": 25000.0,
    "discount_amount": 5000.0,
    "total_amount": 20000.0
  }
}
```

This is a **preview only** — it doesn't reserve the coupon, apply it to anything, or count toward
any redemption limit. Nothing is persisted until you actually complete a checkout with
`coupon_code` set (§4 or §5-single-course below).

**Errors** — always `400`, `message` is the specific reason:

| Message | Meaning |
|---|---|
| `"Invalid coupon code"` | No coupon with that code exists. |
| `"This coupon is no longer active"` | Admin has disabled it. |
| `"This coupon is not active yet"` / `"This coupon has expired"` | Outside its `valid_from`/`valid_until` window. |
| `"This coupon has reached its redemption limit"` | Global `max_redemptions` hit. |
| `"You've already used this coupon"` | You've hit your personal `max_redemptions_per_user`. |
| `"This coupon is only valid for first-time buyers"` | `new_users_only` and you have a prior successful purchase. |
| `"This coupon requires a minimum order of ₦X"` | Your subtotal is below `min_order_amount`. |
| `"This coupon does not apply to any items in your order"` | Coupon is scoped (by course/category) and nothing in your cart/selection qualifies. |
| `"This coupon would reduce your total to zero - it can't be applied"` | Safety guard — a coupon can discount your order, never zero it out. |
| `"Your cart is empty"` / `"No matching courses found"` | Nothing to price against (only when `course_ids` was omitted/empty and your cart is empty, or the ids you passed don't resolve to real courses). |

### Discount computation (so your UI can match the API's math)

1. **Eligible amount**: if the coupon has no `applicable_course_ids`/`applicable_category`, every
   item counts. Otherwise, only items matching either condition count — the rest of the order is
   left at full price.
2. **`PERCENTAGE`**: `discount = eligible_amount × (discount_value / 100)`, then capped at
   `max_discount_amount` if the coupon has one.
3. **`FIXED_AMOUNT`**: `discount = min(discount_value, eligible_amount)` — a flat coupon can never
   discount more than the eligible items are actually worth.
4. **`total_amount = subtotal_amount − discount_amount`**, rounded to 2dp.

**Worked example**: cart has Course A (₦10,000) and Course B (₦15,000) = ₦25,000 subtotal. Coupon
is `PERCENTAGE`, `discount_value: 20`, `max_discount_amount: 1000`, `applicable_course_ids: [A]`.
Eligible amount is just A's ₦10,000 (B doesn't qualify). 20% of ₦10,000 is ₦2,000, but the ₦1,000
cap kicks in → `discount_amount: 1000`, `total_amount: 24000`.

### Using a coupon on a single-course checkout (no cart involved)

```
POST /payments/initialize
```
now additionally accepts:
```json
{
  "transaction_type": "COURSE_PURCHASE",
  "related_id": "c9d8e7f6-....",
  "gateway": "PAYSTACK",
  "save_card": false,
  "coupon_code": "WELCOME20"
}
```
Same discount engine, same error table as above (a single course is just a one-item order for
this purpose). Omit `coupon_code` entirely for a normal, undiscounted purchase — nothing else
about this endpoint changed. `coupon_code` is ignored for `SUBSCRIPTION` transactions; coupons
apply to course purchases only.

---

## 6. Receipts

No new receipt endpoint — a `CART_PURCHASE` transaction's receipt works through the exact same
`GET /payments/transactions/{reference}/receipt` download endpoint and the exact same automatic
post-payment email described in [`PAYMENT_RECEIPT_API.md`](../phase_1/PAYMENT_RECEIPT_API.md). The
only difference is content: a cart receipt lists every purchased course as its own line item, with
a Subtotal / Coupon discount (if any) / Amount Paid breakdown instead of a single course line.
`GET /payments/transactions/me` will show `subtotal_amount` and `discount_amount` alongside the
final `amount` for any transaction a coupon touched (both `0`/absent for a plain, undiscounted
purchase).
