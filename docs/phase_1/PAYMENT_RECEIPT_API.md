# Payment Receipts — Frontend API Reference

Every successful **course purchase** gets a branded PDF receipt. It's emailed to the user
automatically the moment payment succeeds, and it can also be downloaded on-demand, anytime,
via the endpoint below — that's the one your frontend needs to wire up.

## Conventions

- **Auth**: `Authorization: Bearer <access_token>` for a logged-in user (`get_current_user`).
- Unlike other endpoints in this API, the receipt endpoint does **not** return the standard
  `ApiResponse<T>` JSON envelope — it returns the **raw PDF bytes** directly
  (`Content-Type: application/pdf`), because it's meant to be downloaded/opened, not parsed.
- Receipts only exist for `transaction_type = COURSE_PURCHASE` transactions with
  `status = SUCCESS`. Subscription payments don't have a receipt endpoint (yet).

---

## 1. Get the transaction reference

You need a transaction's `reference` (e.g. `TXN_A1B2C3D4E5F6...`) to download its receipt. Get it
from the user's transaction history:

```
GET /payments/transactions/me?page=1&page_size=20
Authorization: Bearer <token>
```

**Response** — `200 OK`, envelope: `PaginatedResponse<TransactionReadDTO>`

```json
{
  "success": true,
  "message": "OK",
  "data": [
    {
      "id": "b1e2c3d4-....",
      "user_id": "a1b2c3d4-....",
      "amount": 25000.0,
      "reference": "TXN_A1B2C3D4E5F6A1B2C3D4",
      "gateway": "PAYSTACK",
      "status": "SUCCESS",
      "transaction_type": "COURSE_PURCHASE",
      "related_id": "c9d8e7f6-....",
      "created_at": "2026-09-02T10:15:00Z",
      "updated_at": "2026-09-02T10:15:03Z"
    }
  ],
  "meta": {
    "page": 1,
    "page_size": 20,
    "total_items": 4,
    "total_pages": 1,
    "has_next": false,
    "has_previous": false
  }
}
```

Only show a "Download receipt" action for rows where `transaction_type === "COURSE_PURCHASE"` and
`status === "SUCCESS"` — every other combination will 400 on download (see §3).

---

## 2. Download the receipt

```
GET /payments/transactions/{reference}/receipt
Authorization: Bearer <token>
```

| Param | Type | Notes |
|---|---|---|
| `reference` | path, string | The transaction's `reference`, from §1. |

**Response** — `200 OK`

```
Content-Type: application/pdf
Content-Disposition: attachment; filename="Receipt-TXN_A1B2C3D4E5F6A1B2C3D4.pdf"

<binary PDF bytes>
```

### Frontend implementation

Because this is a binary response (not JSON) and requires an `Authorization` header, you can't
just point a plain `<a href="...">` at it — the browser won't attach the bearer token. Fetch it as
a `Blob` and trigger the download from that instead:

```ts
async function downloadReceipt(reference: string, accessToken: string) {
  const res = await fetch(`${API_BASE_URL}/payments/transactions/${reference}/receipt`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });

  if (!res.ok) {
    const error = await res.json().catch(() => null);
    throw new Error(error?.message ?? `Failed to download receipt (${res.status})`);
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);

  const a = document.createElement("a");
  a.href = url;
  // Optional: pull the filename Content-Disposition suggests instead of hardcoding it.
  a.download = `Receipt-${reference}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();

  URL.revokeObjectURL(url);
}
```

If you'd rather open it in a new tab (e.g. to preview before saving) instead of forcing a download,
skip the `a.download` attribute and use `window.open(url, "_blank")` instead.

---

## 3. Errors

| Status | When | `message` |
|---|---|---|
| `401` | Missing/invalid/expired token | standard auth error |
| `403` | Transaction belongs to a different user (and caller isn't an admin) | `"You do not have access to this receipt"` |
| `404` | No transaction with that `reference` | `"Transaction not found"` |
| `404` | The course tied to the transaction no longer exists | `"Course not found"` |
| `400` | Transaction is a `SUBSCRIPTION`, not `COURSE_PURCHASE` | `"Receipts are only available for course purchases"` |
| `400` | Transaction `status` isn't `SUCCESS` (e.g. still `PENDING` or `FAILED`) | `"Receipt is only available for successful payments"` |

These error responses **do** use the standard envelope (`ApiErrorResponse` — `{ "success": false,
"message": "..." }`), unlike the successful PDF response.

---

## 4. Notes

- **Admins** can download any user's receipt by reference (same endpoint, no separate admin route)
  — the 403 check only blocks non-admins from downloading someone else's.
- The PDF is generated fresh on every request (not stored/cached), so it always reflects current
  branding — no stale receipts to worry about.
- The same PDF is what's attached to the "payment received" email sent right after checkout, so a
  user re-downloading later gets an identical document.
