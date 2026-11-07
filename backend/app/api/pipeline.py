from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestionRun, Job
from app.db.session import get_session

router = APIRouter(tags=["status"])


class SourceCount(BaseModel):
    source: str
    active_jobs: int


class RunOut(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    fetched: int
    inserted: int
    updated: int
    skipped: int
    errors: int


class PipelineStatus(BaseModel):
    active_jobs: int
    added_last_24h: int
    by_source: list[SourceCount]
    recent_runs: list[RunOut]  # newest first


@router.get("/status/pipeline")
async def pipeline_status(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PipelineStatus:
    """How many jobs are live, where they came from, and the last ingestion runs."""
    since = func.now() - timedelta(hours=24)
    active = await session.scalar(select(func.count()).select_from(Job).where(Job.is_active))
    added = await session.scalar(
        select(func.count()).select_from(Job).where(Job.first_seen_at >= since)
    )
    by_source = await session.execute(
        select(Job.source, func.count())
        .where(Job.is_active)
        .group_by(Job.source)
        .order_by(func.count().desc())
    )
    runs = await session.scalars(
        select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(7)
    )
    return PipelineStatus(
        active_jobs=active or 0,
        added_last_24h=added or 0,
        by_source=[SourceCount(source=s, active_jobs=n) for s, n in by_source],
        recent_runs=[RunOut.model_validate(r, from_attributes=True) for r in runs],
    )
