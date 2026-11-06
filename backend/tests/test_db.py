"""Integration tests against a migrated Postgres + pgvector (TEST_DATABASE_URL)."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import EMBED_DIM
from app.db.models import IngestionRun, Job, Resume

pytestmark = pytest.mark.db


def axis(i: int) -> list[float]:
    """A unit vector along dimension i."""
    vector = [0.0] * EMBED_DIM
    vector[i] = 1.0
    return vector


def make_job(source_id: str, embedding: list[float] | None = None, **kwargs) -> Job:
    return Job(
        source="remotive",
        source_id=source_id,
        url=f"https://example.com/jobs/{source_id}",
        title="Backend Engineer",
        company="Acme",
        description="Build APIs.",
        content_hash=source_id.ljust(64, "0"),
        embedding=embedding,
        embed_model="BAAI/bge-small-en-v1.5" if embedding else None,
        **kwargs,
    )


async def test_cosine_search_returns_nearest_active_job(db_session: AsyncSession) -> None:
    near, far, inactive = axis(0), axis(1), axis(0)
    db_session.add_all(
        [
            make_job("near", near),
            make_job("far", far),
            make_job("inactive", inactive, is_active=False),
            make_job("no-vector"),
        ]
    )
    await db_session.flush()

    query = [0.9, 0.1] + [0.0] * (EMBED_DIM - 2)
    distance = Job.embedding.cosine_distance(query)
    rows = (
        await db_session.execute(
            select(Job.source_id, distance.label("distance"))
            .where(Job.is_active, Job.embedding.is_not(None))
            .order_by(distance)
        )
    ).all()

    assert [r.source_id for r in rows] == ["near", "far"]
    assert rows[0].distance < rows[1].distance


async def test_server_defaults(db_session: AsyncSession) -> None:
    job = make_job("defaults")
    resume = Resume(text="Python developer", parsed={"skills": ["Python"]})
    run = IngestionRun()
    db_session.add_all([job, resume, run])
    await db_session.flush()
    await db_session.refresh(job)
    await db_session.refresh(resume)
    await db_session.refresh(run)

    assert job.is_active is True and job.remote is False and job.skills == []
    assert job.first_seen_at is not None
    assert resume.id is not None and resume.created_at is not None
    assert run.status == "running" and run.inserted == 0 and run.error_details == []


async def test_source_and_source_id_are_unique(db_session: AsyncSession) -> None:
    db_session.add(make_job("dup"))
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(make_job("dup"))
            await db_session.flush()


async def test_embedding_dimension_is_enforced(db_session: AsyncSession) -> None:
    with pytest.raises(Exception, match="expected 384 dimensions"):
        async with db_session.begin_nested():
            db_session.add(make_job("bad-dim", [1.0, 0.0, 0.0]))
            await db_session.flush()
