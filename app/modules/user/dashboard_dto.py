import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.user.activity_entity import ActivityTypeEnum


class UserStatsDTO(BaseModel):
    total_courses_enrolled: int
    quizzes_attempted: int
    completion_rate: float
    total_reviews: int
    in_process_courses: int
    completed_courses: int
    not_started_courses: int
    bookmarked_courses: int


class ActivityLogDTO(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    activity_type: ActivityTypeEnum
    metadata_json: dict | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
