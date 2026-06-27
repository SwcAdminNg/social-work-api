import math
from typing import Generic, Sequence, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")


class PaginationParams:
    """Shared `page`/`page_size` query params. Use as a FastAPI dependency:

        @router.get("/items")
        def list_items(pagination: PaginationParams = Depends()):
            ...
    """

    def __init__(
        self,
        page: int = Query(1, ge=1, description="1-indexed page number"),
        page_size: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    ) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_previous: bool


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard envelope for any paginated list endpoint."""

    success: bool = True
    message: str = "OK"
    data: list[T]
    meta: PaginationMeta

    @classmethod
    def create(
        cls,
        items: Sequence[T],
        total_items: int,
        params: PaginationParams,
        message: str = "OK",
    ) -> "PaginatedResponse[T]":
        total_pages = math.ceil(total_items / params.page_size) if total_items else 0
        return cls(
            data=list(items),
            message=message,
            meta=PaginationMeta(
                page=params.page,
                page_size=params.page_size,
                total_items=total_items,
                total_pages=total_pages,
                has_next=params.page < total_pages,
                has_previous=params.page > 1,
            ),
        )
