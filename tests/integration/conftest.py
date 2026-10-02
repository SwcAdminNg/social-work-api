import os
import uuid

import pytest
import pytest_asyncio

TEST_DB = os.environ.get("TEST_POSTGRES_DB")


def pytest_collection_modifyitems(config, items):
    if TEST_DB:
        return
    skip = pytest.mark.skip(reason="set TEST_POSTGRES_DB=<name>_test to run integration tests")
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def migrated_db():
    """Drop, recreate and migrate the disposable test database once per run."""
    import psycopg2
    from alembic import command
    from alembic.config import Config

    from app.core.config import settings

    assert settings.postgres_db == TEST_DB, "settings were loaded before the test database override"
    conn = psycopg2.connect(
        host=settings.postgres_host, port=settings.postgres_port, user=settings.postgres_user,
        password=settings.postgres_password, dbname="postgres",
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        cur.execute(f'CREATE DATABASE "{TEST_DB}"')
    conn.close()

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "alembic"))
    command.upgrade(cfg, "head")
    return TEST_DB


@pytest_asyncio.fixture(loop_scope="session", scope="session")
async def client(migrated_db):
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest_asyncio.fixture(loop_scope="session", scope="session")
async def make_user(migrated_db):
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token
    from app.modules.user.entity import PlatformEnum, User, UserTypeEnum

    async def factory(first_name: str, user_type: UserTypeEnum = UserTypeEnum.USER) -> tuple[User, dict]:
        suffix = uuid.uuid4().hex[:8]
        async with AsyncSessionLocal() as session:
            user = User(
                first_name=first_name, last_name="Test", email=f"{first_name.lower()}-{suffix}@example.test",
                username=f"{first_name.lower()}_{suffix}", platform=PlatformEnum.NG, user_type=user_type,
                is_active=True,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        token, _ = create_access_token(str(user.id))
        return user, {"Authorization": f"Bearer {token}"}

    return factory
