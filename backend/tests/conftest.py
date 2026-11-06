import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import Settings, get_settings, to_asyncpg_url

APP_ENV_PREFIXES = ("LLM_", "EMBED_", "CORS_ORIGINS", "APP_ENV", "LOG_LEVEL")
ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests see default settings, not whatever provider the developer has configured."""
    for name in list(os.environ):
        if name.startswith(APP_ENV_PREFIXES):
            monkeypatch.delenv(name)


@pytest.fixture
def settings() -> Settings:
    """Settings built from defaults only, ignoring the developer's .env and environment."""
    return Settings(_env_file=None, app_env="test", cors_origins=["http://localhost:3100"])


async def _create_database_if_missing(url: str) -> None:
    parsed = make_url(url)
    admin = parsed.set(drivername="postgresql", database="postgres")
    conn = await asyncpg.connect(admin.render_as_string(hide_password=False))
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", parsed.database
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{parsed.database}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def test_database_url() -> Iterator[str]:
    """TEST_DATABASE_URL, created if missing and migrated to head once per test session.

    Point it at its own database (docker compose uses `matchlens_test`) so tests never
    see the development data.
    """
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("TEST_DATABASE_URL not set")
    url = to_asyncpg_url(raw)
    asyncio.run(_create_database_if_missing(url))

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url  # Alembic's env.py reads settings
    get_settings.cache_clear()
    try:
        command.upgrade(Config(str(ALEMBIC_INI)), "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


@pytest.fixture
async def db_session(test_database_url: str) -> AsyncIterator[AsyncSession]:
    """A session inside a transaction that is rolled back afterwards."""
    engine = create_async_engine(test_database_url)
    async with engine.connect() as conn:
        transaction = await conn.begin()
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()
