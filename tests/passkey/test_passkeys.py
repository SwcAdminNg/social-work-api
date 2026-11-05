"""Passkey registration and sign-in, verified end to end against a software
authenticator that produces real WebAuthn responses (ES256, "none" attestation).
The database is replaced by a tiny fake session."""

import hashlib
import json
import os
import struct
import uuid
from types import SimpleNamespace

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

from app.core.config import settings
from app.modules.passkey import service as passkey_service
from app.modules.passkey.entity import PasskeyCredential
from app.modules.passkey.service import PasskeyService, allowed_origins, device_name_from_user_agent, relying_party_for

ORIGIN = "http://localhost:3000"
RP_ID = "localhost"


# -- software authenticator ----------------------------------------------------


class SoftAuthenticator:
    def __init__(self, user_handle: bytes):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)
        self.user_handle = user_handle
        self.counter = 0

    def _cose_key(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})

    @staticmethod
    def _client_data(kind: str, challenge: str, origin: str) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": origin, "crossOrigin": False}).encode()

    def register(self, options: dict, origin: str = ORIGIN, user_verified: bool = True) -> dict:
        rp_hash = hashlib.sha256(options["rp"]["id"].encode()).digest()
        flags = 0x01 | 0x40 | (0x04 if user_verified else 0)
        attested = bytes(16) + struct.pack(">H", len(self.credential_id)) + self.credential_id + self._cose_key()
        auth_data = rp_hash + bytes([flags]) + struct.pack(">I", self.counter) + attested
        client_data = self._client_data("webauthn.create", options["challenge"], origin)
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        cid = bytes_to_base64url(self.credential_id)
        return {
            "id": cid,
            "rawId": cid,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "attestationObject": bytes_to_base64url(attestation),
                "transports": ["internal", "hybrid"],
            },
            "clientExtensionResults": {},
        }

    def sign_in(self, options: dict, origin: str = ORIGIN, rp_id: str = RP_ID) -> dict:
        self.counter += 1
        auth_data = hashlib.sha256(rp_id.encode()).digest() + bytes([0x01 | 0x04]) + struct.pack(">I", self.counter)
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        cid = bytes_to_base64url(self.credential_id)
        return {
            "id": cid,
            "rawId": cid,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "authenticatorData": bytes_to_base64url(auth_data),
                "signature": bytes_to_base64url(signature),
                "userHandle": bytes_to_base64url(self.user_handle),
            },
            "clientExtensionResults": {},
        }


# -- fake database ---------------------------------------------------------------


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def first(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self.rows))


class FakeSession:
    """Returns stored passkeys for any select; enough for the service's queries."""

    def __init__(self):
        self.passkeys: list[PasskeyCredential] = []
        self.deleted: list[PasskeyCredential] = []
        self.events: list[tuple[str, object]] = []

    async def execute(self, stmt):
        sql = str(stmt)
        params = stmt.compile().params
        rows = [p for p in self.passkeys if p not in self.deleted]
        if "credential_id" in params:
            rows = [p for p in rows if p.credential_id == params["credential_id_1"]] if "credential_id_1" in params else rows
        for key, value in params.items():
            if key.startswith("credential_id"):
                rows = [p for p in rows if p.credential_id == value]
            if key.startswith("user_id"):
                rows = [p for p in rows if p.user_id == value]
        if sql.lstrip().upper().startswith("SELECT PASSKEY_CREDENTIALS.ID") and "credential_id" in sql:
            return FakeResult([(p.id,) for p in rows])
        return FakeResult(rows)

    def add(self, obj):
        obj.id = obj.id or uuid.uuid4()
        self.passkeys.append(obj)

    async def commit(self):
        self.events.append(("commit", None))

    async def refresh(self, obj):
        self.events.append(("refresh", obj))

    async def delete(self, obj):
        self.deleted.append(obj)


@pytest.fixture
def user():
    return SimpleNamespace(
        id=uuid.uuid4(), email="ada@example.com", first_name="Ada", last_name="Obi",
        username="ada", is_active=True, is_suspended=False, last_login_at=None,
    )


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(settings, "webauthn_allowed_origins", "")
    passkey_service._used_tokens.clear()


@pytest.fixture
def login_stubs(monkeypatch, user):
    from app.modules.auth.service import AuthService
    from app.modules.notification.service import NotificationService
    from app.modules.user.repository import UserRepository

    async def get_by_id(self, user_id, include_deleted=False):
        return user if user_id == user.id else None

    async def issue(self, u, extended=False):
        return SimpleNamespace(access_token="access", refresh_token="refresh", token_type="bearer", expires_in=3600, extended=extended)

    async def notify(self, u):
        return None

    async def access(session, u):
        return {}

    captured = {}

    def session_dto(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(UserRepository, "get_by_id", get_by_id)
    monkeypatch.setattr(AuthService, "_issue_token_pair", issue)
    monkeypatch.setattr(NotificationService, "notify_login", notify)
    monkeypatch.setattr(passkey_service, "build_user_access", access)
    monkeypatch.setattr(passkey_service, "AuthSessionDTO", session_dto)
    monkeypatch.setattr(passkey_service.UserReadDTO, "model_validate", classmethod(lambda cls, u: {"id": str(u.id)}))
    return captured


# -- helpers -----------------------------------------------------------------------


def test_origins_and_relying_party(monkeypatch):
    monkeypatch.setattr(settings, "frontend_url", "https://www.socialworknigeria.org")
    origins = allowed_origins()
    assert {"https://www.socialworknigeria.org", "https://socialworknigeria.org", "http://localhost:3000"} <= origins
    assert relying_party_for("https://www.socialworknigeria.org/") == ("https://www.socialworknigeria.org", "socialworknigeria.org")
    with pytest.raises(HTTPException):
        relying_party_for("https://evil.example.com")


@pytest.mark.parametrize(
    "ua,expected",
    [
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36", "Chrome on Windows"),
        ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile Safari/604.1", "Safari on iPhone"),
        ("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 SamsungBrowser/26.0 Chrome/122.0 Mobile Safari/537.36", "Samsung Internet on Android"),
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0 Safari/537.36 Edg/131.0", "Edge on Mac"),
        (None, "Passkey"),
    ],
)
def test_device_names(ua, expected):
    assert device_name_from_user_agent(ua) == expected


# -- end to end ------------------------------------------------------------------


async def register(user, session=None, authenticator=None, name=None):
    session = session or FakeSession()
    service = PasskeyService(session)
    started = await service.start_registration(user, ORIGIN)
    authenticator = authenticator or SoftAuthenticator(user.id.bytes)
    credential = authenticator.register(started["options"])
    passkey = await service.finish_registration(
        user, ORIGIN, started["challenge_token"], credential, name,
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0 Safari/537.36",
    )
    return session, service, authenticator, passkey, started


async def test_registration_requires_discoverable_verified_passkey(user):
    _, _, _, passkey, started = await register(user)
    selection = started["options"]["authenticatorSelection"]
    assert selection["residentKey"] == "required" and selection["userVerification"] == "required"
    assert passkey.name == "Chrome on Windows"
    assert passkey.rp_id == RP_ID
    assert passkey.transports == ["internal", "hybrid"]
    assert base64url_to_bytes(passkey.credential_id)


async def test_registration_rejects_unverified_user(user):
    service = PasskeyService(FakeSession())
    started = await service.start_registration(user, ORIGIN)
    credential = SoftAuthenticator(user.id.bytes).register(started["options"], user_verified=False)
    with pytest.raises(HTTPException) as exc:
        await service.finish_registration(user, ORIGIN, started["challenge_token"], credential, None, None)
    assert exc.value.status_code == 400


async def test_registration_rejects_wrong_origin_in_client_data(user):
    service = PasskeyService(FakeSession())
    started = await service.start_registration(user, ORIGIN)
    credential = SoftAuthenticator(user.id.bytes).register(started["options"], origin="https://evil.example.com")
    with pytest.raises(HTTPException):
        await service.finish_registration(user, ORIGIN, started["challenge_token"], credential, None, None)


async def test_challenge_token_is_single_use(user):
    session = FakeSession()
    service = PasskeyService(session)
    started = await service.start_registration(user, ORIGIN)
    auth = SoftAuthenticator(user.id.bytes)
    await service.finish_registration(user, ORIGIN, started["challenge_token"], auth.register(started["options"]), None, None)
    with pytest.raises(HTTPException) as exc:
        await service.finish_registration(user, ORIGIN, started["challenge_token"], SoftAuthenticator(user.id.bytes).register(started["options"]), None, None)
    assert "already been used" in exc.value.detail


async def test_custom_name_is_kept(user):
    *_, passkey, _ = await register(user, name="  Work laptop  ")
    assert passkey.name == "Work laptop"


async def test_sign_in_with_registered_passkey(user, login_stubs):
    session, service, authenticator, passkey, _ = await register(user)
    started = await service.start_login(ORIGIN, None)
    assert started["options"]["userVerification"] == "required"
    assert not started["options"].get("allowCredentials")  # discoverable: no username needed
    result = await service.finish_login(ORIGIN, started["challenge_token"], authenticator.sign_in(started["options"]), True, "Safari")
    assert result.tokens.extended is True
    assert passkey.sign_count == 1 and passkey.last_used_at is not None
    assert user.last_login_at is not None
    # Regression: the user must be reloaded after the last commit before the
    # response is built, or reading updated_at triggers a lazy load (500 in production).
    last_commit = max(i for i, (kind, _) in enumerate(session.events) if kind == "commit")
    assert any(kind == "refresh" and obj is user for kind, obj in session.events[last_commit + 1:])


async def test_sign_in_with_identifier_limits_allowed_credentials(user, login_stubs, monkeypatch):
    session, service, authenticator, passkey, _ = await register(user)
    from app.modules.user.repository import UserRepository

    async def by_identifier(self, identifier):
        return user if identifier == "ada" else None

    monkeypatch.setattr(UserRepository, "get_by_email_or_username", by_identifier)
    started = await service.start_login(ORIGIN, "ada")
    assert [c["id"] for c in started["options"]["allowCredentials"]] == [passkey.credential_id]
    unknown = await service.start_login(ORIGIN, "nobody")
    assert not unknown["options"].get("allowCredentials")


async def test_sign_in_with_unknown_passkey_is_refused(user, login_stubs):
    session, service, *_ = await register(user)
    started = await service.start_login(ORIGIN, None)
    stranger = SoftAuthenticator(user.id.bytes)
    with pytest.raises(HTTPException) as exc:
        await service.finish_login(ORIGIN, started["challenge_token"], stranger.sign_in(started["options"]), False, None)
    assert exc.value.status_code == 401


async def test_sign_in_with_tampered_signature_is_refused(user, login_stubs):
    session, service, authenticator, *_ = await register(user)
    started = await service.start_login(ORIGIN, None)
    credential = authenticator.sign_in(started["options"])
    credential["response"]["signature"] = bytes_to_base64url(b"\x30\x06\x02\x01\x01\x02\x01\x01")
    with pytest.raises(HTTPException) as exc:
        await service.finish_login(ORIGIN, started["challenge_token"], credential, False, None)
    assert exc.value.status_code == 401


async def test_sign_in_for_suspended_account_is_refused(user, login_stubs):
    session, service, authenticator, *_ = await register(user)
    user.is_suspended = True
    started = await service.start_login(ORIGIN, None)
    with pytest.raises(HTTPException) as exc:
        await service.finish_login(ORIGIN, started["challenge_token"], authenticator.sign_in(started["options"]), False, None)
    assert exc.value.status_code == 403


async def test_existing_passkeys_are_excluded_when_adding_another(user):
    session, service, authenticator, passkey, _ = await register(user)
    again = await service.start_registration(user, ORIGIN)
    assert [c["id"] for c in again["options"]["excludeCredentials"]] == [passkey.credential_id]


async def test_rename_and_remove(user):
    session, service, _, passkey, _ = await register(user)
    renamed = await service.rename(user, passkey.id, "Phone")
    assert renamed.name == "Phone"
    await service.delete(user, passkey.id)
    assert passkey in session.deleted
