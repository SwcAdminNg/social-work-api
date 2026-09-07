# Payment Tax (VAT) Update — Student/Cart API Changes

This document covers **only what changed** on the student-facing purchase flow now that Nigeria
VAT (**7.5%**) is applied to every purchase. It's an addendum to
[`CART_COUPON_STUDENT_API.md`](./CART_COUPON_STUDENT_API.md) and
[`PAYMENT_RECEIPT_API.md`](../phase_1/PAYMENT_RECEIPT_API.md) — read those first for the full
cart/coupon/checkout/receipt flow; this doc just calls out the delta so your integration doesn't
miss it.

**Nothing about the request shapes changed.** No new required fields, no breaking request changes.
The changes are all on the response/money side: a new server-side charge component, and two new
fields on transaction records. Read §3 carefully — there's one gap you need to work around.

---

## 1. What actually changed

Every successful checkout — single-course (`POST /payments/initialize`), cart
(`POST /cart/checkout`), a saved-card charge, and subscription purchases/renewals — now has
**7.5% VAT** added on top of the (coupon-discounted, if applicable) subtotal **before** the
customer is charged. This happens entirely server-side:

```
taxable_amount  = subtotal_amount − discount_amount      (unchanged math, same as before)
tax_amount      = round(taxable_amount × 0.075, 2)        ← NEW
amount_charged  = round(taxable_amount + tax_amount, 2)   ← this is what Paystack actually charges
```

`amount_charged` is what gets sent to the payment gateway and is what the user sees on the
Paystack checkout page — it is **not** the same number as `total_amount` returned by the cart or
coupon-preview endpoints (see §3, this is the important part).

The VAT rate (7.5%) is fixed for now; there's no student-facing endpoint that returns it as a
config value, so if you want to reproduce the math client-side, use `0.075` as a constant (see
§4 for a full worked example).

---

## 2. Where tax now shows up in responses

### `GET /payments/transactions/me` and `GET /payments/transactions` (admin)

`TransactionReadDTO` has two new fields, present on every transaction (both are `0` for
transactions that predate this change):

```json
{
  "id": "b1e2c3d4-....",
  "user_id": "a1b2c3d4-....",
  "amount": 26875.0,
  "subtotal_amount": 25000.0,
  "discount_amount": 0.0,
  "tax_rate": 0.075,
  "tax_amount": 1875.0,
  "reference": "TXN_A1B2C3D4E5F6A1B2C3D4",
  "gateway": "PAYSTACK",
  "status": "SUCCESS",
  "transaction_type": "COURSE_PURCHASE",
  "related_id": "c9d8e7f6-....",
  "created_at": "2026-09-07T10:15:00Z",
  "updated_at": "2026-09-07T10:15:03Z"
}
```

- `amount` is unchanged in *meaning* (the final charged amount) but its *value* is now higher than
  it would have been pre-tax, since it includes `tax_amount`.
- `amount = subtotal_amount − discount_amount + tax_amount`, always.
- This is the endpoint to use if you want to show a user their actual VAT paid on a past order
  (e.g. an order history / invoice screen).

### The PDF receipt and the payment-received email

The receipt (downloaded via `GET /payments/transactions/{reference}/receipt`, and the identical
PDF attached to the automatic post-payment email) now shows a `VAT (7.5%)` line between the
discount line (if any) and "Amount paid". No endpoint change here — same download URL as before,
just new content in the PDF. Nothing for the frontend to do differently to trigger or fetch it.

*(Unrelated to tax, but shipped in the same release: the payment-received email itself now also
includes a "Go to My Dashboard" link and a direct link to each purchased course's detail page. This
is email content only — no API shape change, mentioned here in case your frontend AI is
cross-referencing recent backend changes.)*

---

## 3. The gap: cart & coupon preview endpoints do NOT include tax

This is the one thing to actually build around.

**`GET /cart`** still returns only:
```json
{ "items": [...], "item_count": 2, "subtotal_amount": 25000.0 }
```
No `tax_amount`, no tax-inclusive total. `subtotal_amount` is still just the sum of course prices,
exactly as before tax existed.

**`POST /coupons/validate`** still returns only:
```json
{ "valid": true, "code": "WELCOME20", "subtotal_amount": 25000.0, "discount_amount": 5000.0, "total_amount": 20000.0 }
```
`total_amount` here is **pre-tax** (`subtotal_amount − discount_amount`). Before this change,
`total_amount` was exactly what got charged at checkout. **That is no longer true** — the actual
charge is `total_amount` plus 7.5% VAT. If your cart/checkout UI was showing this `total_amount`
as "amount you'll pay," it is now understating the real charge by 7.5%.

**`POST /cart/checkout`** and **`POST /payments/initialize`** are unchanged in response shape —
still just `{ authorization_url, access_code, reference }`. They never returned an amount
breakdown, so there's nothing that "broke" here, but it also means these endpoints still don't
tell you the tax-inclusive total either.

### Recommended fix on the frontend

Until/unless these preview endpoints are extended to return tax fields directly, compute the
VAT-inclusive estimate client-side using the same formula the backend uses (§1), so what you show
the user matches what Paystack will actually charge them:

```ts
const TAX_RATE = 0.075; // Nigeria VAT — matches the backend's settings.tax_rate

function estimateTotalWithTax(subtotalAmount: number, discountAmount = 0) {
  const taxable = subtotalAmount - discountAmount;
  const taxAmount = Math.round(taxable * TAX_RATE * 100) / 100;
  const totalWithTax = Math.round((taxable + taxAmount) * 100) / 100;
  return { taxAmount, totalWithTax };
}
```

Use this to render a proper breakdown on the cart page and on the coupon-applied state, e.g.:

```
Subtotal:            ₦25,000.00
Coupon (WELCOME20): −₦5,000.00
VAT (7.5%):           ₦1,500.00
─────────────────────────────
Total:               ₦21,500.00   ← what Paystack will actually charge
```

This estimate will match the persisted transaction exactly as long as no rounding edge cases
diverge — the backend rounds `tax_amount` to 2dp the same way. If you want a server-confirmed
number instead of a client estimate, poll `GET /payments/transactions/me` after checkout
completes (or read the `reference`'s transaction after `GET /payments/verify/{reference}`) — that
response always has the authoritative `tax_amount`/`amount`.

---

## 4. Worked example (cart + coupon + tax, end to end)

Cart: Course A (₦10,000) + Course B (₦15,000) = ₦25,000 subtotal.
Coupon `WELCOME20`: 20% off, no cap, applies to everything.

| Step | Value |
|---|---|
| `subtotal_amount` (from `GET /cart` or coupon preview) | ₦25,000.00 |
| `discount_amount` (from `POST /coupons/validate`) | ₦5,000.00 |
| `total_amount` (from `POST /coupons/validate` — **pre-tax**) | ₦20,000.00 |
| `tax_amount` = round(20,000 × 0.075, 2) — **not returned by any preview endpoint, compute client-side** | ₦1,500.00 |
| **Actual amount charged at checkout** (`POST /cart/checkout` → Paystack) | **₦21,500.00** |
| Same number, confirmed server-side after payment, via `GET /payments/transactions/me` → `amount` | ₦21,500.00 |

---

## 5. Quick checklist for the frontend integration

- [ ] Cart page: show `VAT (7.5%)` as its own line, computed client-side from `subtotal_amount` (and
      `discount_amount` if a coupon is applied), using the formula in §3.
- [ ] Don't display `coupons/validate`'s `total_amount` as the final payable amount anymore — it's
      pre-tax. Add the computed `tax_amount` to it before showing "Total".
- [ ] Order history / receipt screens: use `tax_amount` and `amount` directly from
      `GET /payments/transactions/me` — these are authoritative, no client math needed there.
- [ ] No changes needed to how you call `POST /cart/checkout`, `POST /payments/initialize`, or
      `POST /coupons/validate` — request bodies are identical to before.
