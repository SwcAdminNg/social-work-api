# Developer Onboarding Guide

Welcome to the **Social Work Nigeria API** project! This document contains all the necessary information to get you up to speed, install the project locally, understand the architecture, and know about the external services we rely on.

## 1. Tech Stack Overview

This backend is built on the modern Python ecosystem:

- **Framework:** FastAPI
- **Database:** PostgreSQL (with `asyncpg`)
- **ORM:** SQLAlchemy 2.0 (Async)
- **Migrations:** Alembic
- **Caching & Rate Limiting:** Redis
- **Background Tasks & Webhooks:** QStash (Upstash)
- **Validation:** Pydantic (v2)

## 2. External Services & Resources

To run all features of this application in production, we integrate with several third-party services:

1. **PostgreSQL:** The main relational database.
2. **Redis:** Used for caching (e.g., rate limiting, storing temporary session data, caching API responses).
3. **Upstash QStash:** Used for reliable webhook delivery and background task execution without needing a heavy worker like Celery.
4. **SMTP (Gmail):** Used for sending transactional emails (e.g., password reset links).
5. **Cloudflare R2:** S3-compatible object storage for course documents. We generate presigned URLs for secure upload/download directly from the frontend.
6. **Bunny.net Stream:** Used for course video hosting. Supports TUS resumable uploads directly from the frontend to their CDN.
7. **Paystack:** Used for payment processing.

## 3. File & Folder Structure

The application follows a modular, domain-driven structure.

```text
app/
  core/
    config.py          # Settings loaded from .env (pydantic-settings)
    database.py        # Async SQLAlchemy engine/session, declarative Base
  common/
    base_entity.py     # BaseEntity: common columns like id, created_at, deleted_at (soft deletes)
    base_dto.py        # BaseDTO / CreateDTO / UpdateDTO / AuditDTO definitions
    base_repository.py # Generic CRUD repository, soft-delete aware
    responses.py       # Standardized ApiResponse[T] / ApiErrorResponse envelopes
    pagination.py      # Pagination parameters and responses
  models/
    __init__.py        # Imports all entity modules here so Alembic can discover them
  modules/
    health/            # E.g., GET /health route
    <domain_entity>/   # e.g., 'user', 'course' (One folder per entity/domain)
      entity.py        # SQLAlchemy model (inherits BaseEntity)
      dto.py           # Pydantic schemas/DTOs
      repository.py    # Database interaction (Inherits BaseRepository)
      service.py       # Core business logic
      router.py        # FastAPI endpoints
  main.py              # Application entrypoint, FastAPI initialization, Swagger config
alembic/               # Database migration configurations and versions
```

### Adding a new entity

Whenever you create a new feature/entity, create a folder in `app/modules/`. Make sure you:

1. Define the SQLAlchemy model in `entity.py`.
2. Register it in `app/models/__init__.py`.
3. Create the corresponding `dto.py`, `repository.py`, `service.py`, and `router.py`.
4. Generate a new database migration.

## 4. Local Installation & Setup

### Prerequisites

- **Python:** 3.11+ (Recommended 3.13)
- **PostgreSQL:** Running locally. Easiest way is via Docker:
  ```bash
  docker run --name social-workers-db -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=social_workers -p 5432:5432 -d postgres:16
  ```
- **Redis:** Running locally. Easiest way is via Docker:
  ```bash
  docker run --name social-workers-redis -p 6379:6379 -d redis:7
  ```

### Step-by-Step Setup

1. **Activate the Virtual Environment:**
   A virtual environment is located at `venv/`.
   - Windows (PowerShell): `.\venv\Scripts\Activate.ps1`
   - Mac/Linux/Git Bash: `source venv/Scripts/activate` or `source venv/bin/activate`

2. **Install Dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

3. **Configure the Environment:**
   Make sure you have an `.env` file in the root directory (copy from `.env.example`).
   Ensure that the PostgreSQL and Redis connection strings match your local setup:

   ```env
   POSTGRES_USER=postgres
   POSTGRES_PASSWORD=postgres
   POSTGRES_HOST=localhost
   POSTGRES_PORT=5432
   POSTGRES_DB=social_workers
   REDIS_URL=redis://localhost:6379/0
   ```

   _Note: For testing third-party integrations (like Paystack, Bunny.net, R2, QStash), you will need to fill in the respective sandbox/test credentials in your `.env`._

4. **Run Database Migrations:**
   Apply existing migrations to build your database schema:

   ```bash
   alembic upgrade head
   ```

5. **Start the API Server:**

   ```bash
   uvicorn app.main:app --reload
   ```

6. **Verify the API is running:**
   - Interactive API Docs (Swagger UI): http://127.0.0.1:8000/docs
   - API Documentation (ReDoc): http://127.0.0.1:8000/redoc
   - Health Check: http://127.0.0.1:8000/health

## 5. Helpful Commands & Tips

- **Generate a new DB Migration:**
  After updating or adding a new entity:
  ```bash
  alembic revision --autogenerate -m "description of your changes"
  ```
- **Rollback a Migration:**

  ```bash
  alembic downgrade -1
  ```

- **Seeding the certificate:**
  ```bash
  python -m app.scripts.seed_certificate_template --sample-out sample.pdf
  ```

Welcome aboard and happy coding!
