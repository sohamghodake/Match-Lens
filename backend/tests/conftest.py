import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import Settings, to_asyncpg_url

APP_ENV_PREFIXES = ("LLM_", "EMBED_", "CORS_ORIGINS", "APP_ENV", "LOG_LEVEL")


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


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """A session on TEST_DATABASE_URL inside a transaction that is rolled back afterwards,
    so tests can run against the dev database without leaving rows behind."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    engine = create_async_engine(to_asyncpg_url(url))
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
