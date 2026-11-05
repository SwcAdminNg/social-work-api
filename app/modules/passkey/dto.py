import uuid
from datetime import datetime
from typing import Any

from fastapi import Query
from pydantic import Field, computed_field, field_validator

from app.common.base_dto import BaseDTO, CreateDTO

# Well-known authenticator models (AAGUIDs), so people recognise where a passkey lives.
KNOWN_AUTHENTICATORS: dict[str, str] = {
    "fbfc3007-154e-4ecc-8c0b-6e020557d7bd": "iCloud Keychain",
    "dd4ec289-e01d-41c9-bb89-70fa845d4bf2": "iCloud Keychain",
    "ea9b8d66-4d01-1d21-3ce4-b6b48cb575d4": "Google Password Manager",
    "adce0002-35bc-c60a-648b-0b25f1f05503": "Chrome on Mac",
    "08987058-cadc-4b81-b6e1-30de50dcbe96": "Windows Hello",
    "9ddd1817-af5a-4672-a2b9-3e3dd95000a9": "Windows Hello",
    "6028b017-b1d4-4c02-b4b3-afcdafc96bb2": "Windows Hello",
    "53414d53-554e-4700-0000-000000000000": "Samsung Pass",
    "bada5566-a7aa-401f-bd96-45619a55120d": "1Password",
    "d548826e-79b4-db40-a3d8-11116f7e8349": "Bitwarden",
}


def provider_for(aaguid: str | None) -> str | None:
    return KNOWN_AUTHENTICATORS.get((aaguid or "").lower())


class _OriginDTO(CreateDTO):
    # The page origin the browser ceremony runs on, e.g. "https://www.socialworknigeria.org".
    # Only origins on the server's allow-list are accepted.
    origin: str = Field(min_length=8, max_length=255)


class PasskeyRegistrationOptionsRequestDTO(_OriginDTO):
    pass


class PasskeyRegistrationVerifyRequestDTO(_OriginDTO):
    challenge_token: str = Field(min_length=10)
    credential: dict[str, Any]
    name: str | None = Field(default=None, max_length=100)

    @field_validator("name", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class PasskeyLoginOptionsRequestDTO(_OriginDTO):
    # Optional: when the visitor typed an email or username, only their passkeys are offered.
    identifier: str | None = Field(default=None, max_length=255)


class PasskeyCheckRequestDTO(_OriginDTO):
    identifier: str = Field(min_length=1, max_length=255)


class PasskeyCheckResponseDTO(BaseDTO):
    available: bool


class PasskeyLoginVerifyRequestDTO(_OriginDTO):
    challenge_token: str = Field(min_length=10)
    credential: dict[str, Any]
    keep_logged_in: bool = False


class PasskeyRenameRequestDTO(CreateDTO):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class PasskeyOptionsResponseDTO(BaseDTO):
    # PublicKeyCredentialCreationOptionsJSON / RequestOptionsJSON for the browser.
    options: dict[str, Any]
    challenge_token: str


class PasskeyReadDTO(BaseDTO):
    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None = None
    device_type: str | None = None
    backed_up: bool = False
    transports: list[str] | None = None
    aaguid: str | None = None
    rp_id: str
    created_user_agent: str | None = None
    last_used_user_agent: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def provider(self) -> str | None:
        """Where the passkey is stored, when recognisable (e.g. "iCloud Keychain")."""
        return provider_for(self.aaguid)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def synced(self) -> bool:
        """True for passkeys that sync across the user's devices."""
        return self.device_type == "multi_device" or self.backed_up


class PasskeyOwnerDTO(BaseDTO):
    id: uuid.UUID
    first_name: str | None = None
    last_name: str | None = None
    email: str
    username: str | None = None


class AdminPasskeyReadDTO(PasskeyReadDTO):
    user: PasskeyOwnerDTO


class AdminPasskeyFilterParams:
    def __init__(
        self,
        user_id: uuid.UUID | None = Query(None, description="Only passkeys belonging to this user"),
        search: str | None = Query(None, description="Search by user name, email, username or device name"),
    ) -> None:
        self.user_id = user_id
        self.search = search
