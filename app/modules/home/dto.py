from pydantic import BaseModel

class HomeStatsDTO(BaseModel):
    total_number_of_students: int
    number_of_published_courses: int
    completion_rate_of_course_by_enrolled_users: float
