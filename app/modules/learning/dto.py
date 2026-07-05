import uuid
from typing import Any

from pydantic import BaseModel

from app.common.base_dto import BaseDTO
from app.modules.course.dto import CourseReadDTO
from app.modules.course.entity import CourseItemTypeEnum


class EnrolledCourseDTO(CourseReadDTO):
    progress_percent: int
    is_completed: bool


class LearningItemDTO(BaseDTO):
    id: uuid.UUID
    title: str
    item_type: CourseItemTypeEnum
    is_completed: bool


class LearningSectionDTO(BaseDTO):
    id: uuid.UUID
    title: str
    items: list[LearningItemDTO]


class CourseCurriculumDTO(BaseDTO):
    course_id: uuid.UUID
    progress_percent: int
    is_completed: bool
    sections: list[LearningSectionDTO]


class QuizQuestionDTO(BaseDTO):
    id: uuid.UUID
    text: str
    allow_multiple_answers: bool
    options: list[dict[str, Any]]  # id, text


class LearningItemContentDTO(BaseDTO):
    id: uuid.UUID
    title: str
    item_type: CourseItemTypeEnum
    is_completed: bool
    
    # Optional fields depending on item_type
    video_url: str | None = None
    document_url: str | None = None
    questions: list[QuizQuestionDTO] | None = None


class QuizSubmitDTO(BaseModel):
    answers: dict[uuid.UUID, list[uuid.UUID]]  # Question ID -> List of chosen Option IDs


class QuizResultDTO(BaseDTO):
    score: float
    passed: bool
    correct_answers: dict[uuid.UUID, list[uuid.UUID]]  # Question ID -> List of correct Option IDs
