"""Stage 1: the nearest active jobs by cosine similarity (pgvector, HNSW index)."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job
from app.matching.schema import MatchFilters
from app.parsing.locations import eligible_places

# An HNSW scan returns at most ef_search rows (default 40), however high the LIMIT, so
# it is raised above the candidate count. Filters are applied after the scan, so give
# them headroom too.
EF_SEARCH = 250

_iterative_scan: bool | None = None


@dataclass
class Candidate:
    job: Job
    similarity: float


async def _supports_iterative_scan(session: AsyncSession) -> bool:
    """pgvector 0.8+ can keep scanning until filtered queries fill the LIMIT."""
    global _iterative_scan
    if _iterative_scan is None:
        version = await session.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        parts = tuple(int(p) for p in (version or "0").split(".")[:2])
        _iterative_scan = parts >= (0, 8)
    return _iterative_scan


async def retrieve(
    session: AsyncSession,
    vector: list[float],
    *,
    embed_model: str,
    filters: MatchFilters,
    limit: int,
    now: datetime,
) -> list[Candidate]:
    await session.execute(text(f"SET LOCAL hnsw.ef_search = {EF_SEARCH}"))
    if await _supports_iterative_scan(session):
        await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))

    distance = Job.embedding.cosine_distance(vector)
    query = (
        select(Job, (1 - distance).label("similarity"))
        # Vectors from different embedding models aren't comparable.
        .where(Job.is_active, Job.remote, Job.embed_model == embed_model)
        .order_by(distance)
        .limit(limit)
    )
    if filters.posted_within_days:
        cutoff = now - timedelta(days=filters.posted_within_days)
        query = query.where(
            or_(Job.posted_at >= cutoff, and_(Job.posted_at.is_(None), Job.first_seen_at >= cutoff))
        )
    if filters.country:
        open_to_you = Job.regions.overlap(eligible_places(filters.country))
        if filters.include_unspecified:
            open_to_you = or_(open_to_you, func.cardinality(Job.regions) == 0)
        query = query.where(open_to_you)
    if filters.seniority:
        query = query.where(or_(Job.seniority.in_(filters.seniority), Job.seniority.is_(None)))

    rows = (await session.execute(query)).all()
    # relaxed_order may return rows slightly out of order; stage 2 re-sorts anyway.
    return [Candidate(job=row.Job, similarity=float(row.similarity)) for row in rows]
