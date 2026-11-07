"""Rate limits, the shared sample resume, the pipeline status page, CORS for previews."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import EMBED_DIM, Settings
from app.core.ratelimit import RateLimiter
from app.db.models import IngestionRun, Job, Resume
from app.db.session import get_session
from app.llm.client import get_llm_client
from app.llm.embeddings import get_embedder
from app.main import create_app
from app.parsing.schema import LLMResume, LLMRole


def test_sliding_window() -> None:
    limiter = RateLimiter()
    assert limiter.hit("upload", "1.2.3.4", 2, 3600, now=0) is None
    assert limiter.hit("upload", "1.2.3.4", 2, 3600, now=10) is None
    assert limiter.hit("upload", "1.2.3.4", 2, 3600, now=20) == 3580  # wait for the oldest
    assert limiter.hit("upload", "5.6.7.8", 2, 3600, now=20) is None  # per IP
    assert limiter.hit("ats", "1.2.3.4", 2, 3600, now=20) is None  # per action
    assert limiter.hit("upload", "1.2.3.4", 2, 3600, now=3601) is None  # window moved on


class FakeLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def structured[T: BaseModel](self, prompt: str, schema: type[T], **_: object) -> T:
        self.calls += 1
        return LLMResume(  # type: ignore[return-value]
            seniority="senior", skills=["Python"],
            roles=[LLMRole(title="Senior Backend Engineer", company="Ledgerly", start="2022-03",
                           end="Present")],
        )  # fmt: skip


class FakeEmbedder:
    model_name = "fake"
    dim = EMBED_DIM

    async def embed_query(self, text: str) -> list[float]:
        return [0.1] * EMBED_DIM


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM()


def make_client(settings: Settings, llm: FakeLLM, session: AsyncSession | None = None):
    app = create_app(settings, run_sweeper=False)
    app.dependency_overrides[get_llm_client] = lambda: llm
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    if session is not None:

        async def session_override() -> AsyncIterator[AsyncSession]:
            yield session

        app.dependency_overrides[get_session] = session_override
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_rate_limit_returns_429_with_retry_after(settings: Settings, llm: FakeLLM) -> None:
    limited = settings.model_copy(update={"rate_limit_uploads_per_hour": 2})
    async with make_client(limited, llm) as client:
        codes = [
            (await client.post("/resumes", files={"file": ("a.txt", b"x")})).status_code
            for _ in range(3)
        ]
        blocked = await client.post("/resumes", files={"file": ("a.txt", b"x")})
    assert codes == [415, 415, 429]  # rejected files still count
    assert int(blocked.headers["retry-after"]) > 3500
    assert "try again in about" in blocked.json()["detail"]

    off = settings.model_copy(
        update={"rate_limit_uploads_per_hour": 0, "rate_limit_enabled": False}
    )
    async with make_client(off, llm) as client:
        assert (await client.post("/resumes", files={"file": ("a.txt", b"x")})).status_code == 415


@pytest.mark.db
async def test_sample_resume_is_parsed_once_and_shared(
    settings: Settings, llm: FakeLLM, db_session: AsyncSession
) -> None:
    async with make_client(settings, llm, db_session) as client:
        first = (await client.post("/resumes/sample")).json()
        second = (await client.post("/resumes/sample")).json()
    assert first["sample"] is True and first["id"] == second["id"]
    assert first["profile"]["roles"][0]["title"] == "Senior Backend Engineer"
    assert llm.calls == 1

    # Once it expires, the next visitor gets a fresh one.
    stored = await db_session.get(Resume, first["id"])
    stored.created_at = datetime.now(UTC) - timedelta(hours=25)
    await db_session.flush()
    async with make_client(settings, llm, db_session) as client:
        third = (await client.post("/resumes/sample")).json()
    assert third["id"] != first["id"] and llm.calls == 2


@pytest.mark.db
async def test_pipeline_status(settings: Settings, llm: FakeLLM, db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            Job(source="remotive", source_id="s1", url="u", title="t", company="c",
                description="d", content_hash="h1".ljust(64, "0")),
            Job(source="remotive", source_id="s2", url="u", title="t", company="c",
                description="d", content_hash="h2".ljust(64, "0"), is_active=False),
            IngestionRun(status="success", fetched=10, inserted=1),
        ]
    )  # fmt: skip
    await db_session.flush()
    active = await db_session.scalar(select(func.count()).select_from(Job).where(Job.is_active))
    async with make_client(settings, llm, db_session) as client:
        body = (await client.get("/status/pipeline")).json()
    assert body["active_jobs"] == active
    assert {"source": "remotive", "active_jobs": 1} in body["by_source"]
    assert body["recent_runs"][0]["fetched"] == 10


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        ("https://match-lens.vercel.app", True),
        ("https://match-lens-git-feature-x-soham.vercel.app", True),
        ("https://evil.vercel.app", False),
    ],
)
async def test_cors_regex_for_preview_deployments(
    settings: Settings, llm: FakeLLM, origin: str, allowed: bool
) -> None:
    previews = settings.model_copy(
        update={
            "cors_origins": [],
            "cors_origin_regex": r"https://match-lens(-[a-z0-9-]+)?\.vercel\.app",
        }
    )
    async with make_client(previews, llm) as client:
        response = await client.get("/health", headers={"Origin": origin})
    assert (response.headers.get("access-control-allow-origin") == origin) is allowed
