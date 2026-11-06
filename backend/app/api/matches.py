import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import Resume
from app.db.retention import resume_cutoff
from app.db.session import get_session
from app.llm.client import LLMClient, get_llm_client
from app.llm.embeddings import Embedder, get_embedder
from app.matching.schema import MatchesOut, MatchFilters
from app.matching.service import find_matches
from app.parsing.locations import COUNTRIES, country_options
from app.parsing.schema import Seniority

router = APIRouter(tags=["matches"])


@router.get("/resumes/{resume_id}/matches", responses={404: {}})
async def get_matches(
    resume_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    llm: Annotated[LLMClient, Depends(get_llm_client)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
    settings: Annotated[Settings, Depends(get_settings)],
    posted_within_days: Annotated[int | None, Query(ge=1, le=365)] = None,
    seniority: Annotated[list[Seniority] | None, Query()] = None,
    country: Annotated[
        str | None,
        Query(description="ISO code; ANY for no filter; omitted = the resume's country"),
    ] = None,
    include_unspecified: bool = True,
    refresh: bool = False,
) -> MatchesOut:
    """Ranked remote jobs for a resume. Results are cached per resume and filter set;
    `refresh=true` recomputes them."""
    resume = await session.scalar(
        select(Resume).where(Resume.id == resume_id, Resume.created_at >= resume_cutoff())
    )
    if resume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found or expired.")
    if country is None:
        country = (resume.parsed or {}).get("country")
    elif country.upper() == "ANY":
        country = None
    elif country.upper() not in COUNTRIES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown country {country!r}.")
    filters = MatchFilters(
        posted_within_days=posted_within_days,
        seniority=seniority,
        country=country.upper() if country else None,
        include_unspecified=include_unspecified,
    )
    return await find_matches(
        session, resume, llm=llm, embedder=embedder, settings=settings,
        filters=filters, refresh=refresh,
    )  # fmt: skip


class Country(BaseModel):
    code: str
    name: str


@router.get("/locations/countries")
async def list_countries() -> list[Country]:
    """Countries the location filter understands, for the UI."""
    return [Country(code=code, name=name) for code, name in country_options()]
