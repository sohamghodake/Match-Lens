from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import get_session
from app.main import create_app


def client_for(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_health_reports_ok_and_models(settings: Settings) -> None:
    async with client_for(create_app(settings)) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["llm_model"] == settings.llm_model
    assert body["embed_model"] == "BAAI/bge-small-en-v1.5"
    assert "api_key" not in response.text


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [("http://localhost:3100", True), ("https://evil.example", False)],
)
async def test_cors_only_allows_configured_origins(
    settings: Settings, origin: str, allowed: bool
) -> None:
    async with client_for(create_app(settings)) as client:
        response = await client.get("/health", headers={"Origin": origin})
    assert (response.headers.get("access-control-allow-origin") == origin) is allowed


async def test_health_db_reports_unreachable_database(settings: Settings) -> None:
    class BrokenSession:
        async def scalar(self, *_args, **_kwargs):
            raise ConnectionRefusedError("db down")

    async def broken_session() -> AsyncIterator[BrokenSession]:
        yield BrokenSession()

    app = create_app(settings)
    app.dependency_overrides[get_session] = broken_session
    async with client_for(app) as client:
        response = await client.get("/health/db")
    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "pgvector": None,
        "migration": None,
        "detail": "ConnectionRefusedError",
    }


@pytest.mark.db
async def test_health_db_against_real_database(
    settings: Settings, db_session: AsyncSession
) -> None:
    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app = create_app(settings)
    app.dependency_overrides[get_session] = session_override
    async with client_for(app) as client:
        response = await client.get("/health/db")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["pgvector"]
    assert body["migration"] == "0001"
