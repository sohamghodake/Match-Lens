"""End-to-end ingestion runs against Postgres, replaying synthetic feeds from disk.

The test session is rolled back afterwards. Assertions look only at this test's own
rows (company names like "Testco"), so real jobs in a dev database don't interfere.
"""

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import EMBED_DIM
from app.db.models import Job
from ingestion.run import run

pytestmark = pytest.mark.db

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)


class FakeEmbedder:
    model_name = "fake-embedder"
    dim = EMBED_DIM

    def __init__(self) -> None:
        self.embedded: list[str] = []

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.embedded += texts
        return [[0.5] * EMBED_DIM for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [0.5] * EMBED_DIM


def gh_job(job_id: int, title: str, location: str = "Remote", body: str = "Python and Go") -> dict:
    return {
        "id": job_id,
        "title": title,
        "absolute_url": f"https://job-boards.greenhouse.io/testco/jobs/{job_id}",
        "company_name": "Testco",
        "location": {"name": location},
        "first_published": "2026-10-20T10:00:00+00:00",
        "content": f"&lt;p&gt;{body}&lt;/p&gt;",
    }


def feeds() -> dict[str, Any]:
    return {
        "greenhouse/samsara": {  # a real board token, so the source knows it
            "jobs": [
                gh_job(1, "Backend Engineer"),
                gh_job(2, "Frontend Engineer"),
                gh_job(3, "Account Executive"),  # not tech: filtered
                gh_job(4, "Data Engineer", location="San Francisco, CA"),  # not remote
            ]
        },
        "remotive/_all": {
            "jobs": [
                {
                    "id": 77, "url": "https://remotive.com/remote-jobs/77",
                    "title": "Platform Engineer", "company_name": "Testco Two",
                    "candidate_required_location": "Worldwide",
                    "publication_date": "2026-11-01T00:00:00", "salary": "",
                    "description": "<p>Kubernetes</p>", "tags": [],
                }
            ]
        },
        "remoteok/_all": [
            {"legal": "terms"},
            {  # the same posting as on Remotive: a cross-source duplicate
                "id": "9", "epoch": int((NOW - timedelta(days=5)).timestamp()),
                "position": "Platform Engineer", "company": "Testco Two Inc", "location": "",
                "description": "<p>Kubernetes, but described differently</p>", "tags": [],
                "url": "https://remoteok.com/remote-jobs/9",
            },
            {  # posted 40 days ago: expires under the 30-day rule for rolling feeds
                "id": "10", "epoch": int((NOW - timedelta(days=40)).timestamp()),
                "position": "Android Developer", "company": "Testco Three", "location": "",
                "description": "<p>Kotlin</p>", "tags": [], "url": "https://remoteok.com/remote-jobs/10",
            },
        ],
    }  # fmt: skip


def write_feeds(directory: Path, data: dict[str, Any]) -> Path:
    for key, payload in data.items():
        path = directory / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
    return directory


async def ours(session: AsyncSession) -> dict[str, Job]:
    rows = await session.scalars(select(Job).where(Job.company.like("Testco%")))
    return {f"{j.source}:{j.source_id}": j for j in rows}


async def ingest(session: AsyncSession, replay: Path, embedder: FakeEmbedder, now: datetime = NOW):
    return await run(
        ["remotive", "remoteok", "greenhouse"],
        session=session, embedder=embedder, replay=replay, now=now,
    )  # fmt: skip


async def test_second_run_adds_nothing(db_session: AsyncSession, tmp_path: Path) -> None:
    replay = write_feeds(tmp_path / "feeds", feeds())
    embedder = FakeEmbedder()

    first = await ingest(db_session, replay, embedder)
    jobs = await ours(db_session)
    assert sorted(jobs) == ["greenhouse:samsara:1", "greenhouse:samsara:2", "remotive:77"]
    gh = first.stats["greenhouse"]
    assert (gh.fetched, gh.kept, gh.inserted) == (4, 2, 2)
    assert gh.filtered == {"not_tech": 1, "not_remote": 1}
    assert first.stats["remoteok"].duplicates == 1
    assert first.stats["remoteok"].filtered == {"stale": 1}  # 40 days old, never stored
    assert jobs["greenhouse:samsara:1"].embed_model == "fake-embedder"
    assert jobs["greenhouse:samsara:1"].skills == ["Python", "Go"]
    assert len(embedder.embedded) == 3

    second = await ingest(db_session, replay, embedder, now=NOW + timedelta(days=1))
    assert sum(s.inserted for s in second.stats.values()) == 0
    assert sum(s.updated for s in second.stats.values()) == 0
    assert second.stats["greenhouse"].unchanged == 2
    assert len(embedder.embedded) == 3  # nothing re-embedded
    assert len(await ours(db_session)) == 3
    assert second.stats["remoteok"].deactivated == 0
    assert (await ours(db_session))["greenhouse:samsara:1"].last_seen_at == NOW + timedelta(days=1)


async def test_changed_job_is_updated_and_reembedded(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    data = feeds()
    embedder = FakeEmbedder()
    await ingest(db_session, write_feeds(tmp_path / "a", data), embedder)

    changed = copy.deepcopy(data)
    changed["greenhouse/samsara"]["jobs"][0]["content"] = "&lt;p&gt;Rust and Kafka&lt;/p&gt;"
    result = await ingest(
        db_session, write_feeds(tmp_path / "b", changed), embedder, NOW + timedelta(hours=1)
    )

    assert result.stats["greenhouse"].updated == 1
    assert len(embedder.embedded) == 4
    job = (await ours(db_session))["greenhouse:samsara:1"]
    assert job.skills == ["Rust", "Kafka"]


async def test_closed_jobs_deactivate_only_when_their_feed_was_fetched(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    data = feeds()
    await ingest(db_session, write_feeds(tmp_path / "a", data), FakeEmbedder())

    # The board no longer lists job 2: it closed.
    closed = copy.deepcopy(data)
    closed["greenhouse/samsara"]["jobs"] = closed["greenhouse/samsara"]["jobs"][:1]
    later = NOW + timedelta(days=1)
    await ingest(db_session, write_feeds(tmp_path / "b", closed), FakeEmbedder(), later)
    jobs = await ours(db_session)
    assert jobs["greenhouse:samsara:1"].is_active is True
    assert jobs["greenhouse:samsara:2"].is_active is False

    # Next day the board fails to fetch (no page at all): its jobs must stay as they are.
    failed = {k: v for k, v in data.items() if not k.startswith("greenhouse/")}
    result = await ingest(
        db_session, write_feeds(tmp_path / "c", failed), FakeEmbedder(), later + timedelta(days=1)
    )
    assert result.stats["greenhouse"].pages_ok == 0
    assert (await ours(db_session))["greenhouse:samsara:1"].is_active is True

    # And when it reappears, job 2 comes back to life.
    await ingest(
        db_session, write_feeds(tmp_path / "d", data), FakeEmbedder(), later + timedelta(days=2)
    )
    assert (await ours(db_session))["greenhouse:samsara:2"].is_active is True


async def test_dry_run_writes_nothing(db_session: AsyncSession, tmp_path: Path) -> None:
    result = await run(
        ["greenhouse"], session=db_session, embedder=FakeEmbedder(),
        replay=write_feeds(tmp_path, feeds()), dry_run=True, now=NOW,
    )  # fmt: skip
    assert result.stats["greenhouse"].inserted == 2  # what it would insert
    assert await ours(db_session) == {}


async def test_unchanged_jobs_get_refreshed_derived_fields(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    replay = write_feeds(tmp_path / "feeds", feeds())
    embedder = FakeEmbedder()
    await ingest(db_session, replay, embedder)
    # Simulate rows stored by older rules: stale skills and no places.
    job = (await ours(db_session))["greenhouse:samsara:1"]
    job.skills, job.regions = ["Git"], []
    await db_session.flush()

    result = await ingest(db_session, replay, embedder, NOW + timedelta(days=1))
    assert result.stats["greenhouse"].unchanged == 2
    assert result.stats["greenhouse"].refreshed == 1
    await db_session.refresh(job)
    assert job.skills == ["Python", "Go"] and job.regions == []  # "Remote" names no place
    assert len(embedder.embedded) == 4  # re-embedded, since skills feed the embedding
