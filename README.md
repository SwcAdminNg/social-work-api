# Social Workers API

FastAPI + PostgreSQL backend. This README walks through install → setup → running the app.

## 1. Prerequisites

- Python 3.11+ (this project was set up with 3.13)
- PostgreSQL running locally or reachable (Docker is easiest):

  ```bash
  docker run --name social-workers-db -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=social_workers -p 5432:5432 -d postgres:16
  ```

## 2. Install dependencies

A virtualenv already exists at `venv/`. Activate it and install:

```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

(Bash/Git Bash: `source venv/Scripts/activate`)

## 3. Configure environment

Copy `.env.example` to `.env` (already done) and adjust the Postgres credentials to match your database:

```
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=social_workers
```

## 4. Run database migrations

Alembic is wired up but there are no entities yet — once you add one (see below) generate and apply a migration:

```powershell
alembic revision --autogenerate -m "create users table"
alembic upgrade head
```

To roll back the last migration: `alembic downgrade -1`

## 5. Run the API

```powershell
uvicorn app.main:app --reload
```

- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc
- Health check: http://127.0.0.1:8000/health

## Project layout

```
app/
  core/
    config.py          # Settings loaded from .env (pydantic-settings)
    database.py        # Async SQLAlchemy engine/session, declarative Base
  common/
    base_entity.py      # BaseEntity: id, created_at, updated_at, deleted_at,
                         # restored_at, created_by, updated_by, deleted_by, restored_by
    base_dto.py          # BaseDTO / CreateDTO / UpdateDTO / AuditDTO
    base_repository.py   # Generic CRUD repository, soft-delete aware
    responses.py         # ApiResponse[T] / ApiErrorResponse envelopes
    pagination.py        # PaginationParams + PaginatedResponse[T]
  models/
    __init__.py          # Import every entity module here so Alembic sees it
  modules/
    health/
      router.py           # GET /health
    <entity>/              # One folder per entity, e.g. modules/user/
      entity.py             #   SQLAlchemy model (inherits BaseEntity)
      dto.py                #   Pydantic DTOs (inherit BaseDTO/AuditDTO)
      repository.py         #   Inherits BaseRepository
      service.py            #   Business logic
      router.py             #   FastAPI routes
  main.py                  # FastAPI app, Swagger config, exception handlers
alembic/
  env.py, versions/        # Migration scaffold
```

## Adding a new entity (the pattern to follow each time)

1. **Entity** — `app/modules/<name>/entity.py`:

   ```python
   from sqlalchemy.orm import Mapped, mapped_column
   from app.common.base_entity import BaseEntity

   class User(BaseEntity):
       __tablename__ = "users"
       email: Mapped[str] = mapped_column(unique=True, nullable=False)
       full_name: Mapped[str] = mapped_column(nullable=False)
   ```

2. **Register it** in `app/models/__init__.py` so Alembic/SQLAlchemy see it:

   ```python
   from app.modules.user.entity import User  # noqa: F401
   ```

3. **DTOs** — `app/modules/<name>/dto.py`:

   ```python
   from app.common.base_dto import AuditDTO, CreateDTO, UpdateDTO

   class UserCreateDTO(CreateDTO):
       email: str
       full_name: str

   class UserUpdateDTO(UpdateDTO):
       full_name: str | None = None

   class UserReadDTO(AuditDTO):
       email: str
       full_name: str
   ```

4. **Repository** — `app/modules/<name>/repository.py`:

   ```python
   from app.common.base_repository import BaseRepository
   from app.modules.user.entity import User

   class UserRepository(BaseRepository[User]):
       def __init__(self, session):
           super().__init__(session, User)
   ```

5. **Router** — use `ApiResponse[UserReadDTO]` for single items and
   `PaginatedResponse[UserReadDTO]` (built via `PaginatedResponse.create(...)`) for lists.

6. **Migration**:

   ```powershell
   alembic revision --autogenerate -m "create users table"
   alembic upgrade head
   ```
