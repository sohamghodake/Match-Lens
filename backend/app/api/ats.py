from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ats import score
from app.ats.analyze import analyze
from app.ats.schema import AtsReport, AtsRequest, JobSummary
from app.core.ratelimit import rate_limit
from app.db.models import Job, Resume
from app.db.retention import resume_cutoff
from app.db.session import get_session
from app.llm.client import LLMClient, get_llm_client
from app.parsing.schema import ResumeProfile

router = APIRouter(tags=["ats"])


@router.post(
    "/ats",
    responses={404: {}, 429: {}},
    dependencies=[Depends(rate_limit("ats", "rate_limit_ats_per_hour"))],
)
async def ats_score(
    request: AtsRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    llm: Annotated[LLMClient, Depends(get_llm_client)],
) -> AtsReport:
    """Score a resume against a job description, explaining every point deducted."""
    resume = await session.scalar(
        select(Resume).where(Resume.id == request.resume_id, Resume.created_at >= resume_cutoff())
    )
    if resume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found or expired.")
    if request.job_id is not None:
        job = await session.get(Job, request.job_id)
        if job is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
        text = f"{job.title}\n{job.description}"
    else:
        text = request.job_description or ""

    profile = ResumeProfile.model_validate(resume.parsed)
    file_facts = (resume.meta or {}).get("file", {})
    jd = await analyze(text, llm)

    keywords_part, keywords = score.score_keywords(
        jd.required, jd.preferred, resume.text, profile.skills
    )
    parts = [
        keywords_part,
        score.score_sections(resume.text, file_facts, has_location=bool(profile.location)),
        score.score_formatting(file_facts),
        score.score_seniority(
            score.Fit(
                resume_level=profile.seniority,
                resume_years=profile.total_years_experience,
                job_level=jd.seniority,
                job_min_years=jd.min_years,
            )
        ),
    ]
    return AtsReport(
        resume_id=resume.id,
        generated_at=datetime.now(UTC),
        score=round(sum(p.points for p in parts), 1),
        parts=parts,
        keywords=keywords,
        job=JobSummary(title=jd.title, seniority=jd.seniority, min_years=jd.min_years),
        analysis_method=jd.method,
    )
