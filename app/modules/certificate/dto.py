import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.certificate.entity import CertificateBorderStyleEnum


class CertificateTemplateBaseDTO(BaseModel):
    name: str = Field(max_length=150)
    title_text: str = Field(default="Certificate of Completion", max_length=150)
    subtitle_text: str | None = Field(default="This certificate is proudly presented to", max_length=255)
    body_text: str = Field(
        default=(
            "for successfully completing the course “{course_title}” "
            "on {completion_date}, demonstrating dedication and mastery of the material."
        )
    )
    organization_name: str = Field(default="Social Workers Academy", max_length=150)
    footer_text: str | None = Field(default=None, max_length=255)
    signature_name: str | None = Field(default=None, max_length=150)
    signature_title: str | None = Field(default=None, max_length=150)
    primary_color: str = Field(default="#0B3D2E", max_length=7)
    accent_color: str = Field(default="#D4AF37", max_length=7)
    background_color: str = Field(default="#FFFDF7", max_length=7)
    text_color: str = Field(default="#1F2937", max_length=7)
    font_family: str = Field(default="Helvetica", max_length=50)
    border_style: CertificateBorderStyleEnum = CertificateBorderStyleEnum.CLASSIC


class CertificateTemplateCreateDTO(CertificateTemplateBaseDTO):
    pass


class CertificateTemplateUpdateDTO(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    title_text: str | None = Field(default=None, max_length=150)
    subtitle_text: str | None = Field(default=None, max_length=255)
    body_text: str | None = None
    organization_name: str | None = Field(default=None, max_length=150)
    footer_text: str | None = Field(default=None, max_length=255)
    signature_name: str | None = Field(default=None, max_length=150)
    signature_title: str | None = Field(default=None, max_length=150)
    primary_color: str | None = Field(default=None, max_length=7)
    accent_color: str | None = Field(default=None, max_length=7)
    background_color: str | None = Field(default=None, max_length=7)
    text_color: str | None = Field(default=None, max_length=7)
    font_family: str | None = Field(default=None, max_length=50)
    border_style: CertificateBorderStyleEnum | None = None
    is_active: bool | None = None


class CertificateTemplateReadDTO(CertificateTemplateBaseDTO):
    id: uuid.UUID
    owner_id: uuid.UUID | None
    logo_url: str | None
    signature_image_url: str | None
    is_active: bool
    is_global: bool = False
    created_at: datetime

    @classmethod
    def from_entity(cls, entity) -> "CertificateTemplateReadDTO":
        return cls(
            id=entity.id,
            owner_id=entity.owner_id,
            name=entity.name,
            title_text=entity.title_text,
            subtitle_text=entity.subtitle_text,
            body_text=entity.body_text,
            organization_name=entity.organization_name,
            footer_text=entity.footer_text,
            signature_name=entity.signature_name,
            signature_title=entity.signature_title,
            signature_image_url=entity.signature_image_url,
            logo_url=entity.logo_url,
            primary_color=entity.primary_color,
            accent_color=entity.accent_color,
            background_color=entity.background_color,
            text_color=entity.text_color,
            font_family=entity.font_family,
            border_style=entity.border_style,
            is_active=entity.is_active,
            is_global=entity.owner_id is None,
            created_at=entity.created_at,
        )


class CertificateImageUploadRequestDTO(BaseModel):
    file_name: str
    content_type: str | None = None


class CertificateImageUploadResponseDTO(BaseModel):
    upload_url: str
    image_url: str


class CourseCertificateSettingsUpdateDTO(BaseModel):
    certificate_enabled: bool | None = None
    # Explicit null clears the course's own template (falls back to a global one).
    certificate_template_id: uuid.UUID | None = None
    clear_template: bool = False


class CourseCertificateSettingsReadDTO(BaseModel):
    certificate_enabled: bool
    certificate_template_id: uuid.UUID | None
    effective_template: CertificateTemplateReadDTO | None


class CertificateReadDTO(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    course_title: str
    recipient_name: str
    certificate_number: str
    verification_code: str
    issued_at: datetime
    pdf_url: str
    verify_url: str


class PublicCertificateVerifyDTO(BaseModel):
    valid: bool
    recipient_name: str | None = None
    course_title: str | None = None
    certificate_number: str | None = None
    issued_at: datetime | None = None
    pdf_url: str | None = None
