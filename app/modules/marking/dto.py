import enum
import uuid
from datetime import datetime

from pydantic import Field

from app.common.base_dto import BaseDTO
from app.modules.governance.dto import UserSummaryDTO
from app.modules.marking.entity import LearnerResultStatusEnum, MarkRecommendationEnum


class ModerationActionEnum(str, enum.Enum):
    APPROVE = "APPROVE"  # agree with the marker's score and feedback
    AMEND = "AMEND"  # moderated score/feedback replace the marker's
    RETURN = "RETURN"  # send back to the marker to re-mark


class ModerateMarkDTO(BaseDTO):
    action: ModerationActionEnum
    score: float | None = Field(default=None, ge=0, le=100, description="Required for AMEND")
    feedback: str | None = Field(default=None, description="AMEND: replacement feedback for the learner")
    note: str | None = Field(default=None, max_length=5000, description="Required for RETURN and AMEND")


class DisputeMarkDTO(BaseDTO):
    note: str = Field(min_length=5, max_length=5000)


class ApproveMarkDTO(BaseDTO):
    final_score: float | None = Field(
        default=None, ge=0, le=100, description="Defaults to the moderated score; required to settle a dispute"
    )
    final_feedback: str | None = None
    note: str | None = Field(default=None, max_length=2000)
    publish: bool = Field(default=False, description="Release the result to the learner straight away")


class PublishMarksDTO(BaseDTO):
    mark_ids: list[uuid.UUID] = Field(default_factory=list)
    all_approved: bool = Field(default=False, description="Publish every APPROVED mark for this item")


class EssayMarkReadDTO(BaseDTO):
    id: uuid.UUID
    created_at: datetime
    submission_id: uuid.UUID
    item_id: uuid.UUID
    course_id: uuid.UUID
    learner: UserSummaryDTO | None = None
    attempt_no: int
    status: LearnerResultStatusEnum
    marker: UserSummaryDTO | None = None
    score: float
    feedback: str | None = None
    recommendation: MarkRecommendationEnum | None = None
    submitted_for_moderation_at: datetime | None = None
    moderator: UserSummaryDTO | None = None
    moderated_score: float | None = None
    moderated_feedback: str | None = None
    moderation_note: str | None = None
    moderated_at: datetime | None = None
    disputed: bool = False
    dispute_note: str | None = None
    approved_by: UserSummaryDTO | None = None
    approved_at: datetime | None = None
    final_score: float | None = None
    final_feedback: str | None = None
    approval_note: str | None = None
    published_at: datetime | None = None
    available_actions: list[str] = []


class PublishMarksResultDTO(BaseDTO):
    published: int
    skipped: list[uuid.UUID] = []
