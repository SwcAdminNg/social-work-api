import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class JadMessageDTO(BaseModel):
    id: uuid.UUID
    role: str  # "user" | "assistant"
    content: str
    suggestions: list[str] = Field(default_factory=list)
    # 1 helpful, -1 not helpful, absent when not rated.
    feedback: int | None = None
    created_at: datetime


class JadStateDTO(BaseModel):
    # False when JAD AI is switched off or not configured: hide the assistant.
    available: bool
    # "document" | "scorm" | "quiz"
    lesson_kind: str
    first_name: str
    # Starter questions for the pills and the composer's placeholder.
    suggestions: list[str]
    messages: list[JadMessageDTO]
    max_message_chars: int


class JadAskDTO(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    # The practice-quiz question on screen, if any.
    question_id: uuid.UUID | None = None
    # Tapped from a suggestion pill: stand-alone, so it may be answered from the cache.
    from_suggestion: bool = False


class JadFeedbackDTO(BaseModel):
    # true helpful, false not helpful, null clears the rating.
    helpful: bool | None = None
