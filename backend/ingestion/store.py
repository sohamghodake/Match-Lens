"""Database writes for an ingestion run. Everything here runs in one transaction, so a
failed run leaves the jobs table as it was."""

from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job
from ingestion.dedupe import StoredJob
from ingestion.normalize import NormalizedJob

INSERT_BATCH = 500  # stays well under asyncpg's 32,767 bind-parameter limit
STALE_AFTER = timedelta(days=30)


async def load_stored(session: AsyncSession) -> list[StoredJob]:
    rows = await session.execute(
        select(
            Job.id, Job.source, Job.source_id, Job.content_hash, Job.company, Job.title,
            Job.is_active, Job.skills, Job.seniority, Job.regions,
        )
    )  # fmt: skip
    return [StoredJob(*row) for row in rows]


def _values(job: NormalizedJob, vector: list[float] | None, embed_model: str | None) -> dict:
    return {
        "source": job.source,
        "source_id": job.source_id,
        "url": job.url,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "remote": job.remote,
        "salary": job.salary,
        "seniority": job.seniority,
        "description": job.description,
        "skills": job.skills,
        "regions": job.regions,
        "posted_at": job.posted_at,
        "content_hash": job.content_hash,
        "embedding": vector,
        "embed_model": embed_model if vector is not None else None,
        "is_active": True,
    }


async def insert_jobs(
    session: AsyncSession,
    jobs: Sequence[tuple[NormalizedJob, list[float] | None]],
    embed_model: str | None,
    now: datetime,
) -> int:
    inserted = 0
    for start in range(0, len(jobs), INSERT_BATCH):
        rows = [
            {**_values(job, vector, embed_model), "first_seen_at": now, "last_seen_at": now}
            for job, vector in jobs[start : start + INSERT_BATCH]
        ]
        # ON CONFLICT keeps reruns idempotent even if two runs ever overlap.
        result = await session.execute(
            insert(Job).values(rows).on_conflict_do_nothing(constraint="uq_jobs_source_source_id")
        )
        inserted += result.rowcount or 0
    return inserted


async def update_jobs(
    session: AsyncSession,
    jobs: Sequence[tuple[int, NormalizedJob, list[float] | None]],
    embed_model: str | None,
    now: datetime,
) -> None:
    for job_id, job, vector in jobs:
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(**_values(job, vector, embed_model), last_seen_at=now, updated_at=now)
        )


async def touch_jobs(session: AsyncSession, ids: Sequence[int], now: datetime) -> None:
    """Seen again, unchanged: keep it active and record when we last saw it."""
    if ids:
        await session.execute(
            update(Job).where(Job.id.in_(ids)).values(last_seen_at=now, is_active=True)
        )


async def deactivate_unseen(session: AsyncSession, source: str, scope: str, now: datetime) -> int:
    """For a complete feed that was fetched successfully: anything in its scope that
    we didn't see this run has been taken down."""
    query = update(Job).where(Job.source == source, Job.is_active, Job.last_seen_at < now)
    if scope != "*":
        query = query.where(Job.source_id.startswith(f"{scope}:", autoescape=True))
    result = await session.execute(query.values(is_active=False))
    return result.rowcount or 0


async def deactivate_stale(session: AsyncSession, source: str, now: datetime) -> int:
    """For rolling feeds (Remote OK): a job can't be checked once it leaves the feed,
    so it expires 30 days after posting."""
    cutoff = now - STALE_AFTER
    result = await session.execute(
        update(Job)
        .where(Job.source == source, Job.is_active)
        .where((Job.posted_at < cutoff) | (Job.posted_at.is_(None) & (Job.first_seen_at < cutoff)))
        .values(is_active=False)
    )
    return result.rowcount or 0


async def deactivate_rejected(
    session: AsyncSession, keys: Sequence[tuple[str, str]]
) -> dict[str, int]:
    """Jobs still in a feed that the filters now reject (e.g. after a filter change) stop
    being shown, rather than lingering until they expire."""
    counts: dict[str, int] = {}
    by_source: dict[str, list[str]] = {}
    for source, source_id in keys:
        by_source.setdefault(source, []).append(source_id)
    for source, ids in by_source.items():
        for start in range(0, len(ids), INSERT_BATCH):
            result = await session.execute(
                update(Job)
                .where(Job.source == source, Job.source_id.in_(ids[start : start + INSERT_BATCH]))
                .where(Job.is_active)
                .values(is_active=False)
            )
            counts[source] = counts.get(source, 0) + (result.rowcount or 0)
    return counts


async def refresh_derived(
    session: AsyncSession,
    jobs: Sequence[tuple[int, NormalizedJob, list[float] | None]],
    embed_model: str | None,
) -> None:
    """Unchanged postings whose derived fields (skills, seniority, places) differ from
    what the current rules produce: update them, and the embedding when given."""
    for job_id, job, vector in jobs:
        values: dict = {"skills": job.skills, "seniority": job.seniority, "regions": job.regions}
        if vector is not None:
            values |= {"embedding": vector, "embed_model": embed_model}
        await session.execute(update(Job).where(Job.id == job_id).values(**values))
