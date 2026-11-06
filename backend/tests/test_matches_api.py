"""GET /resumes/{id}/matches against Postgres, with a fake LLM and hand-made vectors."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import EMBED_DIM, Settings
from app.db.models import Job, MatchResult, Resume
from app.db.session import get_session
from app.llm.client import LLMError, get_llm_client
from app.llm.embeddings import get_embedder
from app.main import create_app
from app.matching.rerank import RankedJob, RerankResult
from app.matching.service import RATE_LIMITED_NOTE

pytestmark = pytest.mark.db

MODEL = "fake-embedder"


def vec(*weights: float) -> list[float]:
    v = [0.0] * EMBED_DIM
    for i, w in enumerate(weights):
        v[i] = w
    return v


class FakeEmbedder:
    model_name = MODEL
    dim = EMBED_DIM

    async def embed_query(self, text: str) -> list[float]:
        return vec(1.0)


class FakeLLM:
    """Scores jobs in reverse of the order it was given them, to prove the re-rank wins."""

    def __init__(self) -> None:
        self.calls = 0
        self.error: Exception | None = None

    async def structured_detailed[T: BaseModel](self, prompt: str, schema: type[T], **_: object):
        self.calls += 1
        if self.error:
            raise self.error
        count = prompt.count("\n[")  # job cards start with "[n]"
        jobs = [
            RankedJob(job=n, score=10 + 4 * n, reason=f"reason {n}", missing_skills=["Kafka"])
            for n in range(1, count + 1)
        ]

        class Result:
            value = RerankResult(jobs=jobs)
            model = "fake-llm"
            prompt_tokens = 1000
            completion_tokens = 200

        return Result()


def job(n: int, similarity_axis: list[float], **kw: object) -> Job:
    return Job(
        source="greenhouse", source_id=f"test:{n}", url=f"https://example.com/{n}",
        title=kw.pop("title", f"Backend Engineer {n}"), company=kw.pop("company", "Testco"),
        description="Requirements: Python and Kafka.", content_hash=f"{n}".ljust(64, "0"),
        skills=kw.pop("skills", ["Python", "Kafka"]), embedding=vec(*similarity_axis),
        embed_model=kw.pop("embed_model", MODEL), remote=True, **kw,
    )  # fmt: skip


@pytest.fixture
async def seeded(db_session: AsyncSession) -> Resume:
    db_session.add_all(
        [
            job(1, [1.0, 0.1]),
            job(2, [1.0, 0.3]),
            job(3, [1.0, 0.5], seniority="senior"),
            job(4, [1.0, 0.2], is_active=False),  # closed: never shown
            job(5, [1.0, 0.0], embed_model="other-model"),  # vectors from another model
            job(6, [1.0, 0.4], posted_at=datetime.now(UTC) - timedelta(days=60)),
            job(7, [1.0, 0.11], title="Backend Engineer 1"),  # same role, another location
        ]
    )
    resume = Resume(
        text="resume",
        parsed={
            "headline": "Backend Engineer",
            "seniority": "junior",
            "total_years_experience": 1,
            "skills": ["Python"],
            "roles": [],
            "education": [],
            "projects": [],
        },  # fmt: skip
        embedding=vec(1.0),
        embed_model=MODEL,
        meta={},
    )
    db_session.add(resume)
    await db_session.flush()
    return resume


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def client(settings: Settings, db_session: AsyncSession, llm: FakeLLM) -> httpx.AsyncClient:
    app = create_app(settings, run_sweeper=False)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_llm_client] = lambda: llm
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def titles(body: dict) -> list[str]:
    return [m["job"]["title"] for m in body["matches"]]


async def test_matches_are_reranked_and_cached(
    client: httpx.AsyncClient, seeded: Resume, llm: FakeLLM, db_session: AsyncSession
) -> None:
    async with client:
        first = (await client.get(f"/resumes/{seeded.id}/matches")).json()
        second = (await client.get(f"/resumes/{seeded.id}/matches")).json()

    assert first["reranked"] is True and first["cached"] is False
    assert first["candidates"] == 5  # 7 jobs minus the closed one and the other model's
    # One entry per company + title (job 7 duplicates job 1); the fake LLM reverses order.
    assert sorted(titles(first)) == sorted(f"Backend Engineer {n}" for n in (1, 2, 3, 6))
    scores = [m["score"] for m in first["matches"]]
    assert scores == sorted(scores, reverse=True)
    top = first["matches"][0]
    assert top["reason"].startswith("reason") and top["missing_skills"] == ["Kafka"]
    assert top["matched_skills"] == ["Python"]
    assert first["tokens"] == 1200

    assert second["cached"] is True and titles(second) == titles(first)
    assert llm.calls == 1
    assert await db_session.scalar(select(func.count()).select_from(MatchResult)) == 1


async def test_rate_limit_falls_back_and_is_not_cached(
    client: httpx.AsyncClient, seeded: Resume, llm: FakeLLM
) -> None:
    llm.error = LLMError("openai/gpt-oss-120b returned HTTP 429: Rate limit reached")
    async with client:
        body = (await client.get(f"/resumes/{seeded.id}/matches")).json()
        await client.get(f"/resumes/{seeded.id}/matches")
    assert body["reranked"] is False and body["note"] == RATE_LIMITED_NOTE
    assert body["matches"][0]["reason"].startswith("You have 1 of its 2 listed skills")
    assert all(m["llm_score"] is None for m in body["matches"])
    assert llm.calls == 2  # not cached, so the second request tried the LLM again


async def test_filters(client: httpx.AsyncClient, seeded: Resume) -> None:
    async with client:
        recent = (await client.get(f"/resumes/{seeded.id}/matches?posted_within_days=30")).json()
        levels = (await client.get(f"/resumes/{seeded.id}/matches?seniority=junior")).json()
    # Jobs without posted_at fall back to first_seen_at (today); job 6 is 60 days old.
    assert "Backend Engineer 6" not in titles(recent)
    # Seniority filter keeps unlevelled jobs and drops the senior one.
    assert "Backend Engineer 3" not in titles(levels) and "Backend Engineer 1" in titles(levels)


async def test_unknown_or_expired_resume_is_404(
    client: httpx.AsyncClient, seeded: Resume, db_session: AsyncSession
) -> None:
    seeded.created_at = datetime.now(UTC) - timedelta(hours=25)
    await db_session.flush()
    async with client:
        assert (await client.get(f"/resumes/{seeded.id}/matches")).status_code == 404
        missing = "00000000-0000-0000-0000-000000000000"
        assert (await client.get(f"/resumes/{missing}/matches")).status_code == 404


async def test_deleting_a_resume_deletes_its_cached_matches(
    client: httpx.AsyncClient, seeded: Resume, db_session: AsyncSession
) -> None:
    async with client:
        await client.get(f"/resumes/{seeded.id}/matches")
        assert (await client.delete(f"/resumes/{seeded.id}")).status_code == 204
    assert await db_session.scalar(select(func.count()).select_from(MatchResult)) == 0


async def test_concurrent_identical_requests_make_one_llm_call(
    seeded: Resume, llm: FakeLLM, db_session: AsyncSession, settings: Settings
) -> None:
    import asyncio

    from app.matching.schema import MatchFilters
    from app.matching.service import find_matches

    async def one():
        return await find_matches(
            db_session, seeded, llm=llm, embedder=FakeEmbedder(), settings=settings,
            filters=MatchFilters(),
        )  # fmt: skip

    first, second = await asyncio.gather(one(), one())
    assert llm.calls == 1
    assert sorted([first.cached, second.cached]) == [False, True]


async def test_country_filter(
    client: httpx.AsyncClient, seeded: Resume, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            job(20, [1.0, 0.05], title="Remote India Role", regions=["IN"]),
            job(21, [1.0, 0.06], title="Worldwide Role", regions=["WORLDWIDE"]),
            job(22, [1.0, 0.07], title="APAC Role", regions=["APAC"]),
            job(23, [1.0, 0.08], title="US Only Role", regions=["US"]),
        ]
    )
    seeded.parsed = {**seeded.parsed, "country": "IN"}
    await db_session.flush()

    async with client:
        default = (await client.get(f"/resumes/{seeded.id}/matches")).json()
        strict = (
            await client.get(f"/resumes/{seeded.id}/matches?include_unspecified=false")
        ).json()
        anywhere = (await client.get(f"/resumes/{seeded.id}/matches?country=ANY")).json()
        bad = await client.get(f"/resumes/{seeded.id}/matches?country=XX")

    # No country given: the resume's country applies; jobs that don't say where stay in.
    assert default["filters"]["country"] == "IN"
    assert "US Only Role" not in titles(default)
    assert {"Remote India Role", "Worldwide Role", "APAC Role"} <= set(titles(default))
    assert "Backend Engineer 1" in titles(default)  # unspecified
    assert set(titles(strict)) == {"Remote India Role", "Worldwide Role", "APAC Role"}
    assert anywhere["filters"]["country"] is None and "US Only Role" in titles(anywhere)
    assert bad.status_code == 422


async def test_countries_endpoint(client: httpx.AsyncClient) -> None:
    async with client:
        countries = (await client.get("/locations/countries")).json()
    assert {"code": "IN", "name": "India"} in countries
    names = [c["name"] for c in countries]
    assert names == sorted(names)


# ── POST /ats ─────────────────────────────────────────────────────────────────────


class FakeJDLLM(FakeLLM):
    async def structured[T: BaseModel](self, prompt: str, schema: type[T], **_: object) -> T:
        from app.ats.analyze import JDAnalysis

        return JDAnalysis(  # type: ignore[return-value]
            title="Backend Engineer", seniority="junior", required=["Python", "Kafka"]
        )


async def test_ats_with_pasted_description_and_with_job_id(
    settings: Settings, db_session: AsyncSession, seeded: Resume
) -> None:
    app = create_app(settings, run_sweeper=False)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_llm_client] = lambda: FakeJDLLM()
    seeded.text = "Experience\nBuilt things in Python.\nEducation\nBSc\nSkills\nPython"
    seeded.meta = {"file": {"has_email": True, "has_phone": True, "columns": 1, "tables": 0,
                            "pages": 1, "chars": 3000}}  # fmt: skip
    await db_session.flush()
    some_job = await db_session.scalar(select(Job).where(Job.source_id == "test:1"))
    assert some_job is not None

    description = "Backend Engineer. We need Python and Kafka. " * 3
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        pasted = await c.post(
            "/ats", json={"resume_id": str(seeded.id), "job_description": description}
        )
        by_job = await c.post("/ats", json={"resume_id": str(seeded.id), "job_id": some_job.id})
        both = await c.post(
            "/ats",
            json={"resume_id": str(seeded.id), "job_description": description, "job_id": 1},
        )
        neither = await c.post("/ats", json={"resume_id": str(seeded.id)})
        no_job = await c.post("/ats", json={"resume_id": str(seeded.id), "job_id": 999_999})

    assert pasted.status_code == 200 and by_job.status_code == 200
    report = pasted.json()
    assert report["analysis_method"] == "llm"
    assert [(k["keyword"], k["status"]) for k in report["keywords"]] == [
        ("Python", "found"),
        ("Kafka", "missing"),
    ]
    lost = sum(d["points"] for p in report["parts"] for d in p["deductions"])
    assert round(100 - lost, 1) == report["score"]  # every lost point is explained
    assert (both.status_code, neither.status_code, no_job.status_code) == (422, 422, 404)
