from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.config import Settings, get_settings
from app.db.session import get_session

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: Literal["ok"]
    version: str
    llm_model: str
    embed_model: str


class DbHealth(BaseModel):
    status: Literal["ok", "error"]
    pgvector: str | None = None
    migration: str | None = None
    detail: str | None = None


@router.get("/health")
async def health(settings: Annotated[Settings, Depends(get_settings)]) -> Health:
    """Liveness only. It deliberately skips the database: Render polls this endpoint,
    and a DB query on every poll would keep Neon's free compute awake around the clock."""
    return Health(
        status="ok",
        version=__version__,
        llm_model=settings.llm_model,
        embed_model=settings.embed_model or "",
    )


@router.get("/health/db", responses={503: {"model": DbHealth}})
async def health_db(
    response: Response, session: Annotated[AsyncSession, Depends(get_session)]
) -> DbHealth:
    try:
        pgvector = await session.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        has_alembic = await session.scalar(text("SELECT to_regclass('alembic_version')"))
        migration = (
            await session.scalar(text("SELECT version_num FROM alembic_version"))
            if has_alembic
            else None
        )
    except Exception as exc:  # report, don't raise: this endpoint exists to describe failures
        response.status_code = 503
        return DbHealth(status="error", detail=type(exc).__name__)
    return DbHealth(status="ok", pgvector=pgvector, migration=migration)
