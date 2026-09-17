import uuid
from datetime import datetime

from pydantic import EmailStr, Field, model_validator

from app.common.base_dto import AuditDTO, BaseDTO, CreateDTO
from app.modules.auth.dto import USERNAME_PATTERN
from app.modules.instructor_application.entity import InstructorApplicationStatusEnum
from app.modules.user.entity import PlatformEnum


class SubmitInstructorApplicationRequestDTO(CreateDTO):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone_number: str = Field(min_length=1, max_length=20)
    cv_file_name: str = Field(min_length=1, max_length=255)
    cv_content_type: str | None = Field(default=None, max_length=100)


class InstructorApplicationUploadResponseDTO(BaseDTO):
    application_id: uuid.UUID
    upload_url: str
    storage_key: str


class InstructorApplicationReadDTO(AuditDTO):
    first_name: str
    last_name: str
    email: str
    phone_number: str
    cv_file_name: str
    status: InstructorApplicationStatusEnum
    rejection_reason: str | None = None
    reviewed_by: uuid.UUID | None = None
    reviewed_at: datetime | None = None
    user_id: uuid.UUID | None = None


class InstructorApplicationDetailDTO(InstructorApplicationReadDTO):
    cv_download_url: str


class ApproveInstructorApplicationRequestDTO(BaseDTO):
    platform: PlatformEnum


class RejectInstructorApplicationRequestDTO(BaseDTO):
    reason: str | None = Field(default=None, max_length=1000)


class CompleteInstructorSetupRequestDTO(BaseDTO):
    token: str = Field(min_length=1)
    username: str = Field(min_length=3, max_length=30)
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def validate_username_and_passwords(self) -> "CompleteInstructorSetupRequestDTO":
        if not USERNAME_PATTERN.match(self.username.lower()):
            raise ValueError(
                "Username must be 3-30 characters and contain only lowercase letters, "
                "numbers, dots, or underscores"
            )
        self.username = self.username.lower()

        if self.password != self.confirm_password:
            raise ValueError("Password and confirm_password do not match")
        return self
