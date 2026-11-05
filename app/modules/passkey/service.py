"""Passkey (WebAuthn) registration and sign-in.

Ceremonies are stateless on the server: the challenge travels in a short-lived
signed token, and each token can be used once. Passkeys require user
verification (fingerprint, face or device PIN), so a passkey sign-in is
phishing-resistant multi-factor authentication and completes login without a
separate 2FA code.
"""

import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Sequence
from urllib.parse import urlsplit

import jwt
from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, parse_registration_credential_json
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.common.pagination import PaginationParams
from app.core.config import settings
from app.core.security import create_interim_token, decode_access_token
from app.modules.auth.dto import AuthSessionDTO
from app.modules.governance.access_service import build_user_access
from app.modules.notification.service import NotificationService
from app.modules.passkey.dto import AdminPasskeyFilterParams
from app.modules.passkey.entity import PasskeyCredential
from app.modules.user.dto import UserReadDTO
from app.modules.user.entity import User
from app.modules.user.repository import UserRepository

logger = logging.getLogger(__name__)

REGISTER_TOKEN_TYPE = "passkey_register"
LOGIN_TOKEN_TYPE = "passkey_login"
CHALLENGE_MINUTES = 5
CEREMONY_TIMEOUT_MS = 120_000
MAX_PASSKEYS_PER_USER = 10


# -- origins and relying party ---------------------------------------------------


def _variants(url: str) -> set[str]:
    parts = urlsplit(url.strip().rstrip("/"))
    if not parts.scheme or not parts.netloc:
        return set()
    origin = f"{parts.scheme}://{parts.netloc}"
    host = parts.netloc
    if host.startswith("www."):
        return {origin, f"{parts.scheme}://{host[4:]}"}
    if host.count(".") == 1:  # apex domain: also accept www.
        return {origin, f"{parts.scheme}://www.{host}"}
    return {origin}


def allowed_origins() -> set[str]:
    configured = [o for o in (settings.webauthn_allowed_origins or "").split(",") if o.strip()]
    sources = configured or [
        settings.frontend_url,
        settings.instructor_frontend_url,
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
    ]
    origins: set[str] = set()
    for url in sources:
        origins |= _variants(url)
    return origins


def relying_party_for(origin: str) -> tuple[str, str]:
    """Validates the page origin and returns (origin, rp_id). The rp_id is the host
    without a leading "www.", so a passkey works on both www and the bare domain."""
    normalised = origin.strip().rstrip("/")
    if normalised not in allowed_origins():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Passkeys are not available on this site.")
    host = urlsplit(normalised).hostname or ""
    rp_id = host[4:] if host.startswith("www.") else host
    return normalised, rp_id


# -- single-use challenge tokens ---------------------------------------------------

_used_tokens: dict[str, float] = {}
_used_lock = Lock()


def _consume_once(jti: str, expires_at: float) -> None:
    now = time.time()
    with _used_lock:
        for key in [k for k, exp in _used_tokens.items() if exp < now]:
            del _used_tokens[key]
        if jti in _used_tokens:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This passkey request has already been used. Please try again.")
        _used_tokens[jti] = expires_at


def _issue_challenge(subject: str, token_type: str, challenge: bytes, origin: str, rp_id: str, **extra: Any) -> str:
    return create_interim_token(
        subject=subject,
        token_type=token_type,
        expire_minutes=CHALLENGE_MINUTES,
        extra_claims={"challenge": bytes_to_base64url(challenge), "origin": origin, "rp_id": rp_id, "jti": uuid.uuid4().hex, **extra},
    )


def _read_challenge(token: str, token_type: str, origin: str) -> dict:
    try:
        claims = decode_access_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This passkey request has expired. Please try again.")
    if claims.get("type") != token_type or claims.get("origin") != origin.strip().rstrip("/"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This passkey request is not valid. Please try again.")
    _consume_once(str(claims.get("jti")), float(claims.get("exp", time.time() + 600)))
    return claims


# -- friendly device names --------------------------------------------------------


def device_name_from_user_agent(user_agent: str | None) -> str:
    ua = user_agent or ""
    if re.search(r"Edg/", ua):
        browser = "Edge"
    elif re.search(r"OPR/|Opera", ua):
        browser = "Opera"
    elif re.search(r"SamsungBrowser", ua):
        browser = "Samsung Internet"
    elif re.search(r"Firefox/|FxiOS", ua):
        browser = "Firefox"
    elif re.search(r"Chrome/|CriOS", ua):
        browser = "Chrome"
    elif re.search(r"Safari/", ua):
        browser = "Safari"
    else:
        browser = "Browser"

    if re.search(r"iPhone", ua):
        system = "iPhone"
    elif re.search(r"iPad", ua):
        system = "iPad"
    elif re.search(r"Android", ua):
        system = "Android"
    elif re.search(r"Windows", ua):
        system = "Windows"
    elif re.search(r"Mac OS X|Macintosh", ua):
        system = "Mac"
    elif re.search(r"CrOS", ua):
        system = "Chromebook"
    elif re.search(r"Linux", ua):
        system = "Linux"
    else:
        return browser if browser != "Browser" else "Passkey"
    return f"{browser} on {system}"


class PasskeyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)

    # -- queries ----------------------------------------------------------------

    def _select(self):
        return select(PasskeyCredential).where(PasskeyCredential.deleted_at.is_(None))

    async def list_for_user(self, user_id: uuid.UUID) -> Sequence[PasskeyCredential]:
        stmt = self._select().where(PasskeyCredential.user_id == user_id).order_by(PasskeyCredential.created_at.desc())
        return (await self.session.execute(stmt)).scalars().all()

    async def _get_owned(self, user: User, passkey_id: uuid.UUID) -> PasskeyCredential:
        stmt = self._select().where(PasskeyCredential.id == passkey_id, PasskeyCredential.user_id == user.id)
        passkey = (await self.session.execute(stmt)).scalar_one_or_none()
        if passkey is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Passkey not found")
        return passkey

    # -- registration (signed in) -----------------------------------------------

    async def start_registration(self, user: User, origin: str) -> dict:
        origin, rp_id = relying_party_for(origin)
        existing = await self.list_for_user(user.id)
        if len(existing) >= MAX_PASSKEYS_PER_USER:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"You can register up to {MAX_PASSKEYS_PER_USER} passkeys. Remove one to add another.",
            )
        display_name = " ".join(filter(None, [user.first_name, user.last_name])) or user.email
        options = generate_registration_options(
            rp_id=rp_id,
            rp_name=settings.webauthn_rp_name,
            user_id=user.id.bytes,
            user_name=user.email,
            user_display_name=display_name,
            timeout=CEREMONY_TIMEOUT_MS,
            attestation=AttestationConveyancePreference.NONE,
            authenticator_selection=AuthenticatorSelectionCriteria(
                # Discoverable passkeys let people sign in without typing a username.
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=base64url_to_bytes(p.credential_id)) for p in existing if p.rp_id == rp_id
            ],
        )
        token = _issue_challenge(str(user.id), REGISTER_TOKEN_TYPE, options.challenge, origin, rp_id)
        return {"options": json.loads(options_to_json(options)), "challenge_token": token}

    async def finish_registration(
        self, user: User, origin: str, challenge_token: str, credential: dict, name: str | None, user_agent: str | None
    ) -> PasskeyCredential:
        origin, rp_id = relying_party_for(origin)
        claims = _read_challenge(challenge_token, REGISTER_TOKEN_TYPE, origin)
        if claims.get("sub") != str(user.id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This passkey request is not valid. Please try again.")
        try:
            verified = verify_registration_response(
                credential=credential,
                expected_challenge=base64url_to_bytes(claims["challenge"]),
                expected_rp_id=rp_id,
                expected_origin=origin,
                require_user_verification=True,
            )
        except (InvalidRegistrationResponse, ValueError, KeyError, TypeError) as exc:
            logger.info("Passkey registration rejected for %s: %s", user.id, exc)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "We could not verify this passkey. Please try again.")

        credential_id = bytes_to_base64url(verified.credential_id)
        duplicate = (
            await self.session.execute(select(PasskeyCredential.id).where(PasskeyCredential.credential_id == credential_id))
        ).first()
        if duplicate:
            raise HTTPException(status.HTTP_409_CONFLICT, "This passkey is already registered.")

        transports: list[str] | None = None
        try:
            parsed = parse_registration_credential_json(credential)
            transports = [t.value for t in (parsed.response.transports or [])] or None
        except Exception:  # noqa: BLE001 - transports are optional hints
            transports = None

        passkey = PasskeyCredential(
            user_id=user.id,
            credential_id=credential_id,
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            transports=transports,
            aaguid=str(verified.aaguid) if verified.aaguid else None,
            name=((name or "").strip() or device_name_from_user_agent(user_agent))[:100],
            device_type=getattr(verified.credential_device_type, "value", None),
            backed_up=bool(verified.credential_backed_up),
            rp_id=rp_id,
            created_user_agent=(user_agent or "")[:400] or None,
        )
        self.session.add(passkey)
        await self.session.commit()
        await self.session.refresh(passkey)
        return passkey

    # -- management (signed in) -------------------------------------------------

    async def rename(self, user: User, passkey_id: uuid.UUID, name: str) -> PasskeyCredential:
        passkey = await self._get_owned(user, passkey_id)
        passkey.name = name.strip()[:100] or passkey.name
        await self.session.commit()
        await self.session.refresh(passkey)
        return passkey

    async def delete(self, user: User, passkey_id: uuid.UUID) -> None:
        passkey = await self._get_owned(user, passkey_id)
        await self.session.delete(passkey)
        await self.session.commit()

    # -- sign-in (public) -------------------------------------------------------

    async def start_login(self, origin: str, identifier: str | None) -> dict:
        origin, rp_id = relying_party_for(origin)
        allow: list[PublicKeyCredentialDescriptor] = []
        if identifier and identifier.strip():
            user = await self.users.get_by_email_or_username(identifier.strip())
            if user is not None:
                for p in await self.list_for_user(user.id):
                    if p.rp_id != rp_id:
                        continue
                    transports = []
                    for t in p.transports or []:
                        try:
                            transports.append(AuthenticatorTransport(t))
                        except ValueError:
                            pass
                    allow.append(PublicKeyCredentialDescriptor(id=base64url_to_bytes(p.credential_id), transports=transports or None))
        # An unknown identifier gets the same response shape, so this does not reveal who has an account.
        options = generate_authentication_options(
            rp_id=rp_id,
            allow_credentials=allow or None,
            user_verification=UserVerificationRequirement.REQUIRED,
            timeout=CEREMONY_TIMEOUT_MS,
        )
        token = _issue_challenge("anonymous", LOGIN_TOKEN_TYPE, options.challenge, origin, rp_id)
        return {"options": json.loads(options_to_json(options)), "challenge_token": token}

    async def finish_login(
        self, origin: str, challenge_token: str, credential: dict, keep_logged_in: bool, user_agent: str | None
    ) -> AuthSessionDTO:
        origin, rp_id = relying_party_for(origin)
        claims = _read_challenge(challenge_token, LOGIN_TOKEN_TYPE, origin)

        credential_id = str(credential.get("id") or credential.get("rawId") or "")
        stmt = self._select().where(PasskeyCredential.credential_id == credential_id, PasskeyCredential.rp_id == rp_id)
        passkey = (await self.session.execute(stmt)).scalar_one_or_none() if credential_id else None
        if passkey is None:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "This passkey is not registered with your account. Sign in with your password, then add it in Settings.",
            )

        # When the authenticator reports who it belongs to, it must match.
        user_handle = (credential.get("response") or {}).get("userHandle")
        if user_handle:
            try:
                if base64url_to_bytes(user_handle) != passkey.user_id.bytes:
                    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "We could not verify this passkey.")
            except (ValueError, TypeError):
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "We could not verify this passkey.")

        try:
            verified = verify_authentication_response(
                credential=credential,
                expected_challenge=base64url_to_bytes(claims["challenge"]),
                expected_rp_id=rp_id,
                expected_origin=origin,
                credential_public_key=passkey.public_key,
                credential_current_sign_count=passkey.sign_count,
                require_user_verification=True,
            )
        except (InvalidAuthenticationResponse, ValueError, KeyError, TypeError) as exc:
            logger.info("Passkey sign-in rejected for credential %s: %s", passkey.id, exc)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "We could not verify this passkey. Please try again.")

        user = await self.users.get_by_id(passkey.user_id)
        if user is None or not user.is_active:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been deactivated")
        if user.is_suspended:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been suspended")

        now = datetime.now(timezone.utc)
        passkey.sign_count = verified.new_sign_count
        passkey.backed_up = bool(verified.credential_backed_up)
        passkey.last_used_at = now
        passkey.last_used_user_agent = (user_agent or "")[:400] or None
        user.last_login_at = now
        await self.session.commit()

        # Imported here to avoid a circular import with the auth service.
        from app.modules.auth.service import AuthService

        tokens = await AuthService(self.session)._issue_token_pair(user, extended=keep_logged_in)
        try:
            await NotificationService(self.session).notify_login(user)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to create login notification for %s: %s", user.email, exc)
        return AuthSessionDTO(
            user=UserReadDTO.model_validate(user), tokens=tokens, access=await build_user_access(self.session, user)
        )

    # -- admin ------------------------------------------------------------------

    async def admin_list(
        self, pagination: PaginationParams, filters: AdminPasskeyFilterParams
    ) -> tuple[Sequence[tuple[PasskeyCredential, User]], int]:
        stmt = select(PasskeyCredential, User).join(User, User.id == PasskeyCredential.user_id).where(
            PasskeyCredential.deleted_at.is_(None)
        )
        if filters.user_id:
            stmt = stmt.where(PasskeyCredential.user_id == filters.user_id)
        if filters.search and filters.search.strip():
            term = f"%{filters.search.strip()}%"
            stmt = stmt.where(
                or_(
                    User.email.ilike(term),
                    User.username.ilike(term),
                    User.first_name.ilike(term),
                    User.last_name.ilike(term),
                    PasskeyCredential.name.ilike(term),
                )
            )
        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        stmt = stmt.order_by(PasskeyCredential.created_at.desc()).offset(pagination.offset).limit(pagination.limit)
        rows = (await self.session.execute(stmt)).all()
        return [(row[0], row[1]) for row in rows], total

    async def admin_revoke(self, passkey_id: uuid.UUID) -> None:
        stmt = self._select().where(PasskeyCredential.id == passkey_id)
        passkey = (await self.session.execute(stmt)).scalar_one_or_none()
        if passkey is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Passkey not found")
        await self.session.delete(passkey)
        await self.session.commit()
