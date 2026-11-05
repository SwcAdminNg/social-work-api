"""Public contact form: payload validation, abuse limits and the response shape the
website relies on. Persistence is stubbed, so no database is needed."""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.modules.contact_us import router as contact_router
from app.modules.contact_us.dto import ContactUsCreateDTO, ContactUsReadDTO
from app.modules.contact_us.entity import ContactUsCategoryEnum, ContactUsMessage
from app.modules.contact_us.rate_limit import SlidingWindowLimiter, contact_limiter
from app.modules.contact_us.service import ContactUsService

# What the website's contact form sends.
FORM_PAYLOAD = {
    "full_name": "  Ada Obi ",
    "email": "ada@example.com",
    "phone_number": "+234 803 447 1063",
    "subject": "Account or Learning Support",
    "message": " I cannot open my course after paying. ",
    "platform": "NG",
    "category": "account_support",
    "source_page": "/contact",
}


def make(**overrides) -> ContactUsCreateDTO:
    return ContactUsCreateDTO(**{**FORM_PAYLOAD, **overrides})


# --- validation -----------------------------------------------------------


def test_form_payload_is_accepted_and_trimmed():
    dto = make()
    assert dto.full_name == "Ada Obi"
    assert dto.message == "I cannot open my course after paying."
    assert dto.category is ContactUsCategoryEnum.ACCOUNT_SUPPORT
    assert not dto.is_spam


@pytest.mark.parametrize("category", ["courses", "mentorship", "account_support", "partnership", "other", "general"])
def test_every_form_enquiry_type_is_a_valid_category(category):
    assert make(category=category).category.value == category


@pytest.mark.parametrize("phone", ["", "   ", None])
def test_phone_is_optional(phone):
    assert make(phone_number=phone).phone_number is None


@pytest.mark.parametrize("phone", ["+44 (0) 20 7946 0958", "+1-202-555-0143", "08034471063"])
def test_international_phone_formats_are_accepted(phone):
    assert make(phone_number=phone).phone_number == phone


@pytest.mark.parametrize("phone", ["12", "call me", "+234 803 447 1063 ext 9", "1" * 16])
def test_invalid_phone_is_rejected(phone):
    with pytest.raises(ValidationError):
        make(phone_number=phone)


@pytest.mark.parametrize("field,value", [("full_name", "   "), ("message", "  "), ("email", "not-an-email")])
def test_required_fields_are_enforced(field, value):
    with pytest.raises(ValidationError):
        make(**{field: value})


def test_message_has_an_upper_limit():
    with pytest.raises(ValidationError):
        make(message="x" * 5001)


def test_spam_trap_is_detected_and_never_stored():
    dto = make(website="http://spam.example")
    assert dto.is_spam
    assert "website" not in dto.model_dump()


def test_read_dto_exposes_reference_and_label():
    message = ContactUsMessage(**make().model_dump())
    message.id = uuid.UUID("1a2b3c4d-0000-0000-0000-000000000000")
    message.created_at = datetime.now(timezone.utc)
    read = ContactUsReadDTO.model_validate(message)
    assert read.reference == "SWCL-1A2B3C4D"
    assert read.category_label == "Account or Learning Support"


# --- limiter --------------------------------------------------------------


def test_limiter_blocks_after_limit_within_window():
    limiter = SlidingWindowLimiter()
    assert all(limiter.hit("k", 3, 60) for _ in range(3))
    assert not limiter.hit("k", 3, 60)
    assert limiter.hit("other", 3, 60)


# --- endpoint -------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    stored: list[ContactUsMessage] = []

    async def fake_submit(self, payload):
        message = ContactUsMessage(**payload.model_dump())
        message.id = uuid.uuid4()
        message.created_at = datetime.now(timezone.utc)
        stored.append(message)
        return message

    async def fake_db():
        yield None

    monkeypatch.setattr(ContactUsService, "submit", fake_submit)
    monkeypatch.setattr(settings, "contact_notify_email", "")
    app.dependency_overrides[get_db] = fake_db
    contact_limiter.reset()
    with TestClient(app) as test_client:
        test_client.stored = stored
        yield test_client
    app.dependency_overrides.pop(get_db, None)
    contact_limiter.reset()


def test_submit_returns_reference_and_label(client):
    res = client.post("/contact-us", json=FORM_PAYLOAD)
    assert res.status_code == 201, res.text
    data = res.json()["data"]
    assert data["reference"].startswith("SWCL-") and len(data["reference"]) == 13
    assert data["category_label"] == "Account or Learning Support"
    assert data["source_page"] == "/contact"
    assert len(client.stored) == 1


def test_spam_submission_is_refused_and_not_stored(client):
    res = client.post("/contact-us", json={**FORM_PAYLOAD, "website": "x"})
    assert res.status_code == 400
    assert client.stored == []


def test_repeated_submissions_are_rate_limited(client, monkeypatch):
    monkeypatch.setattr(settings, "contact_rate_limit_per_email", 2)
    headers = {"X-Forwarded-For": "203.0.113.7"}
    assert client.post("/contact-us", json=FORM_PAYLOAD, headers=headers).status_code == 201
    assert client.post("/contact-us", json=FORM_PAYLOAD, headers=headers).status_code == 201
    blocked = client.post("/contact-us", json=FORM_PAYLOAD, headers=headers)
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers
    assert len(client.stored) == 2


def test_rate_limit_is_per_visitor_address(client, monkeypatch):
    monkeypatch.setattr(settings, "contact_rate_limit_per_ip", 1)
    first = {**FORM_PAYLOAD, "email": "one@example.com"}
    second = {**FORM_PAYLOAD, "email": "two@example.com"}
    assert client.post("/contact-us", json=first, headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 201
    assert client.post("/contact-us", json=second, headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 429
    assert client.post("/contact-us", json=second, headers={"X-Forwarded-For": "198.51.100.2"}).status_code == 201


def test_notification_email_is_sent_with_reply_to_when_configured(client, monkeypatch):
    sent = {}

    async def fake_send(self, to_email, subject, html_body, attachments=None, reply_to=None):
        sent.update(to=to_email, subject=subject, html=html_body, reply_to=reply_to)

    from app.core.email import EmailService

    monkeypatch.setattr(EmailService, "_send", fake_send)
    monkeypatch.setattr(settings, "contact_notify_email", "inbox@example.org")
    payload = {**FORM_PAYLOAD, "message": "<script>alert(1)</script> help"}
    res = client.post("/contact-us", json=payload)
    assert res.status_code == 201
    assert sent["to"] == "inbox@example.org"
    assert sent["reply_to"] == "ada@example.com"
    assert sent["subject"].startswith("New enquiry: Account or Learning Support (SWCL-")
    assert "<script>" not in sent["html"] and "&lt;script&gt;" in sent["html"]


def test_router_reads_first_forwarded_address():
    class Req:
        headers = {"x-forwarded-for": "203.0.113.9, 10.0.0.1"}
        client = None

    assert contact_router._client_ip(Req()) == "203.0.113.9"


# --- structured details (mentorship forms) ---------------------------------


def test_details_are_kept_in_order_and_blank_answers_dropped():
    dto = make(
        category="mentor_application",
        details=[
            {"label": "Country", "value": " Nigeria "},
            {"label": "Time zone", "value": "  "},
            {"label": "Qualifications", "value": "BSc Social Work"},
        ],
    )
    assert [(d.label, d.value) for d in dto.details] == [("Country", "Nigeria"), ("Qualifications", "BSc Social Work")]
    assert dto.model_dump()["details"][0] == {"label": "Country", "value": "Nigeria"}


def test_all_blank_details_become_none():
    assert make(details=[{"label": "Availability", "value": ""}]).details is None


def test_too_many_details_are_rejected():
    with pytest.raises(ValidationError):
        make(details=[{"label": f"Q{i}", "value": "x"} for i in range(21)])


def test_overlong_detail_value_is_rejected():
    with pytest.raises(ValidationError):
        make(details=[{"label": "Experience", "value": "x" * 1001}])


def test_mentor_application_round_trip(client):
    payload = {
        **FORM_PAYLOAD,
        "category": "mentor_application",
        "source_page": "/mentorship",
        "details": [{"label": "Country", "value": "Ghana"}, {"label": "Time zone", "value": "GMT"}],
    }
    res = client.post("/contact-us", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()["data"]
    assert data["category_label"] == "Mentor Application"
    assert data["details"] == [{"label": "Country", "value": "Ghana"}, {"label": "Time zone", "value": "GMT"}]


def test_notification_email_includes_details(client, monkeypatch):
    sent = {}

    async def fake_send(self, to_email, subject, html_body, attachments=None, reply_to=None):
        sent["html"] = html_body

    from app.core.email import EmailService

    monkeypatch.setattr(EmailService, "_send", fake_send)
    monkeypatch.setattr(settings, "contact_notify_email", "inbox@example.org")
    payload = {**FORM_PAYLOAD, "details": [{"label": "Preferred pathway", "value": "<b>Early career</b>"}]}
    assert client.post("/contact-us", json=payload).status_code == 201
    assert "Preferred pathway" in sent["html"] and "&lt;b&gt;Early career&lt;/b&gt;" in sent["html"]
