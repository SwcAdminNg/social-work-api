import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.base_entity import BaseEntity


class PasskeyCredential(BaseEntity):
    """A WebAuthn credential (passkey) a user registered with a fingerprint, face
    or device PIN. The private key never leaves the user's device; we keep only
    the public key and the counters needed to verify sign-ins."""

    __tablename__ = "passkey_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # base64url credential id, as the browser reports it.
    credential_id: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False, index=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transports: Mapped[list[str] | None] = mapped_column(ARRAY(String(32)), nullable=True)
    # Authenticator model id; identifies e.g. iCloud Keychain or Google Password Manager.
    aaguid: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Friendly name, e.g. "Chrome on Windows". The user can rename it.
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # "multi_device" passkeys sync across the user's devices; "single_device" stay on one.
    device_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    backed_up: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Which site the passkey belongs to (the WebAuthn relying party), e.g. socialworknigeria.org.
    rp_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
