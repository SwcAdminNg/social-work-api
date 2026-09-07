# Tax (VAT) Report — Admin API Reference

Every purchase (course, cart checkout, saved-card charge, and subscription renewal) now has
**7.5% Nigeria VAT** added on top of the discounted subtotal before it's charged. The rate is
snapshotted onto the `Transaction` row at the moment of purchase (`tax_rate`, `tax_amount`), so
historical reports stay accurate even if the rate changes later.

This doc covers the one new endpoint: the admin-only tax report used to see how much VAT has been
collected, so it can be remitted to the government.

## Conventions

- **Auth**: `Authorization: Bearer <access_token>` for an admin user (`get_current_admin_user`) —
  this endpoint 403s for non-admins.
- Only **successful** transactions with `tax_amount > 0` are included.

---

## Get the tax report

```
GET /payments/taxes
GET /payments/taxes?start_date=2026-01-01&end_date=2026-01-31
GET /payments/taxes?page=1&page_size=20
Authorization: Bearer <admin_token>
```

| Param | Type | Notes |
|---|---|---|
| `start_date` | query, `date`, optional | Only include purchases made on or after this date (inclusive). |
| `end_date` | query, `date`, optional | Only include purchases made on or before this date (inclusive). |
| `page` / `page_size` | query, int, optional | Standard pagination (default `page=1`, `page_size=20`, max `100`). |

If both `start_date` and `end_date` are omitted, the report covers every taxed transaction ever
recorded.

**Response** — `200 OK`

```json
{
  "success": true,
  "message": "Tax report retrieved",
  "summary": {
    "tax_rate": 0.075,
    "total_tax_amount": 187500.0,
    "total_taxable_transactions": 42,
    "start_date": "2026-01-01",
    "end_date": "2026-01-31"
  },
  "data": [
    {
      "reference": "TXN_A1B2C3D4E5F6A1B2C3D4",
      "user_id": "a1b2c3d4-....",
      "transaction_type": "COURSE_PURCHASE",
      "subtotal_amount": 25000.0,
      "discount_amount": 0.0,
      "tax_rate": 0.075,
      "tax_amount": 1875.0,
      "amount": 26875.0,
      "created_at": "2026-01-15T10:15:00Z"
    }
  ],
  "meta": {
    "page": 1,
    "page_size": 20,
    "total_items": 42,
    "total_pages": 3,
    "has_next": true,
    "has_previous": false
  }
}
```

### Notes

- `summary.total_tax_amount` is the sum of `tax_amount` across **every** matching transaction for
  the given date range — not just the current page — so it's the number to hand to finance/legal
  regardless of how many pages you page through.
- `amount` is the final amount the customer was charged, i.e. `subtotal_amount - discount_amount +
  tax_amount`.
- `data` is ordered newest-first, same convention as `GET /payments/transactions`.
