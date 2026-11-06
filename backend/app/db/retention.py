"""Uploaded resumes are deleted 24 hours after upload.

Reads filter on the same cutoff, so an expired resume is never served even if the
sweep hasn't run yet (Render's free tier sleeps, pausing background tasks).
"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Resume
from app.db.session import get_sessionmaker

log = logging.getLogger(__name__)

RESUME_RETENTION = timedelta(hours=24)
SWEEP_INTERVAL_SECONDS = 3600


def resume_cutoff() -> ColumnElement[datetime]:
    return func.now() - RESUME_RETENTION


async def purge_expired_resumes(session: AsyncSession) -> int:
    result = await session.execute(delete(Resume).where(Resume.created_at < resume_cutoff()))
    await session.commit()
    return result.rowcount or 0


async def sweep_forever() -> None:
    """Runs for the life of the API process: once at startup, then hourly."""
    while True:
        try:
            async with get_sessionmaker()() as session:
                if deleted := await purge_expired_resumes(session):
                    log.info("deleted %d expired resumes", deleted)
        except Exception:
            log.exception("resume retention sweep failed; will retry")
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
