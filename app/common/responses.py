from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Standard success envelope returned by every endpoint."""

    success: bool = True
    message: str = "OK"
    data: T | None = None


class ApiErrorResponse(BaseModel):
    """Standard error envelope. `errors` carries field-level validation detail when
    available (e.g. FastAPI's RequestValidationError shape)."""

    success: bool = False
    message: str
    errors: list[dict] | None = None
