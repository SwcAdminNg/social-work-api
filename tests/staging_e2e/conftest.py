"""End-to-end run against the *staging* database (not disposable).

Nothing here drops, recreates or deletes anything. The app runs in-process
against the database in env.text.prod; auth is bypassed by inserting tagged
users straight into the table and minting their tokens. Everything created is
tagged `e2e-<run>-...@mailinator.com` and is deliberately left in place so the
run can be inspected afterwards.

Run only with STAGING_E2E_CONFIRM=1 so it can never start by accident.
"""

import os
import uuid

import pytest_asyncio

CONFIRMED = os.environ.get("STAGING_E2E_CONFIRM") == "1"
if not CONFIRMED:
    # A plain `pytest tests` run must never touch staging: skip this folder entirely.
    collect_ignore_glob = ["*"]
else:
    _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for _line in open(os.path.join(_ROOT, "env.text.prod"), encoding="utf-8"):
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        os.environ[_k.strip()] = _v.strip().strip('"').strip("'")
    os.environ["DATABASE_URL"] = ""
    # No real emails, payments, webhooks, queues or video calls from a test run.
    for _key in (
        "RESEND_API_KEY", "QSTASH_TOKEN", "QSTASH_CURRENT_SIGNING_KEY", "QSTASH_NEXT_SIGNING_KEY",
        "PAYSTACK_SECRET_KEY", "PAYSTACK_PUBLIC_KEY", "BUNNY_STREAM_API_KEY", "DAILY_API_KEY",
    ):
        os.environ[_key] = "disabled-for-e2e"
    os.environ["REDIS_URL"] = ""

RUN = uuid.uuid4().hex[:6]


@pytest_asyncio.fixture(loop_scope="session", scope="session")
async def client():
    import httpx

    from app.core.config import settings
    from app.main import app

    print(f"\n[staging-e2e] target {settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db} run={RUN}")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest_asyncio.fixture(loop_scope="session", scope="session")
async def make_user(client):
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token
    from app.modules.user.entity import PlatformEnum, User, UserTypeEnum

    async def factory(first_name: str, user_type: UserTypeEnum = UserTypeEnum.USER) -> tuple[User, dict]:
        suffix = uuid.uuid4().hex[:6]
        async with AsyncSessionLocal() as session:
            user = User(
                first_name=first_name, last_name="Test",
                email=f"e2e-{RUN}-{first_name.lower()}-{suffix}@mailinator.com",
                username=f"e2e_{RUN}_{first_name.lower()}_{suffix}", platform=PlatformEnum.NG,
                user_type=user_type, is_active=True,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        token, _ = create_access_token(str(user.id))
        print(f"[staging-e2e] created {user.user_type.value} {user.email}")
        return user, {"Authorization": f"Bearer {token}"}

    return factory
