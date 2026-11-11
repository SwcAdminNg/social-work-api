"""Order detail: the display-safe payment summary and the route that serves it."""

from datetime import datetime, timezone

from app.main import app
from app.modules.payment.service import payment_summary


def test_payment_summary_keeps_only_display_safe_fields():
    response = {
        "channel": "card",
        "currency": "NGN",
        "paid_at": "2026-11-02T09:15:30.000Z",
        "gateway_response": "Approved",
        "authorization": {
            "authorization_code": "AUTH_secret",
            "signature": "SIG_secret",
            "last4": "4081",
            "exp_month": "12",
            "exp_year": "2030",
            "card_type": "visa ",
            "brand": "visa",
            "bank": "TEST BANK",
        },
        "customer": {"customer_code": "CUS_secret"},
    }

    summary = payment_summary(response)

    assert summary == {
        "channel": "card",
        "card_type": "visa",
        "brand": "visa",
        "last4": "4081",
        "exp_month": "12",
        "exp_year": "2030",
        "bank": "TEST BANK",
        "currency": "NGN",
        "paid_at": datetime(2026, 11, 2, 9, 15, 30, tzinfo=timezone.utc),
        "gateway_message": "Approved",
    }
    assert "secret" not in repr(summary)


def test_payment_summary_handles_missing_or_odd_responses():
    assert payment_summary(None) is None
    assert payment_summary({}) is None
    assert payment_summary({"authorization": "not-a-dict"}) is None

    odd = payment_summary({"channel": "bank_transfer", "paid_at": "yesterday", "authorization": {"last4": "12ab"}})
    assert odd is not None
    assert odd["channel"] == "bank_transfer"
    assert odd["paid_at"] is None
    assert odd["last4"] is None


def test_order_detail_route_is_registered_and_does_not_shadow_list():
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/v1/payments/transactions/me/{reference}" in paths or any(
        p and p.endswith("/payments/transactions/me/{reference}") for p in paths
    )
    assert any(p and p.endswith("/payments/transactions/me") for p in paths)
