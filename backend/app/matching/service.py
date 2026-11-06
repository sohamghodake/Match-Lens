"""Resume -> ranked jobs: retrieve (pgvector), score (hybrid), re-rank (one LLM call).

Re-ranking is an improvement, not a dependency: if the LLM fails or hits a free-tier
rate limit, the stage-2 ranking is returned with rule-based reasons, and that result
isn't cached, so the next request tries the LLM again.
"""

import asyncio
import logging
import re
import time
import weakref
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Job, MatchResult, Resume
from app.llm.client import LLMClient, LLMError
from app.llm.embeddings import Embedder
from app.matching import rerank
from app.matching.retrieve import retrieve
from app.matching.schema import JobOut, MatchesOut, MatchFilters, MatchOut, Timings
from app.matching.score import Scored, rule_reason, score_candidates
from app.parsing.schema import ResumeProfile
from app.parsing.service import embedding_text
from app.parsing.skills import CANONICAL_SKILLS

log = logging.getLogger(__name__)

RATE_LIMITED_NOTE = (
    "The AI ranking hit its free-tier rate limit, so these are ranked by similarity and "
    "skill overlap. Try again in a minute for AI scores and reasons."
)
UNAVAILABLE_NOTE = (
    "The AI ranking was unavailable, so these are ranked by similarity and skill overlap."
)


# One computation per resume + filters at a time: a double-click, a second tab or React's
# dev-mode double effect would otherwise spend the free-tier token budget twice. The
# waiting request then finds the first one's result in the cache. (Per process, which
# is enough for one free-tier server.)
_locks: "weakref.WeakValueDictionary[str, asyncio.Lock]" = weakref.WeakValueDictionary()


def _lock_for(key: str) -> asyncio.Lock:
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


def _ms(seconds: float) -> int:
    return round(seconds * 1000)


def _posting_key(job: Job) -> str:
    return re.sub(r"[^a-z0-9]+", " ", f"{job.company}|{job.title}".lower()).strip()


def _unique_postings(scored: list[Scored], jobs: dict[int, Job]) -> list[Scored]:
    """One entry per company + title: boards often post the same role once per location."""
    seen: set[str] = set()
    unique = []
    for s in scored:
        key = _posting_key(jobs[s.job_id])
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique


def clean_missing(
    suggested: list[str], job_skills: list[str], resume_skills: list[str]
) -> list[str]:
    """Keep the model's "missing skills" only if they are skills (listed by the job or
    known to the dictionary) that the candidate doesn't already have."""
    have = {s.lower() for s in resume_skills}
    listed = {s.lower() for s in job_skills}
    return [
        s
        for s in suggested
        if s.lower() not in have and (s.lower() in listed or s in CANONICAL_SKILLS)
    ][:4]


async def _cached(
    session: AsyncSession, resume_id, key: str, max_age: timedelta, now: datetime
) -> MatchesOut | None:
    row = await session.scalar(
        select(MatchResult)
        .where(
            MatchResult.resume_id == resume_id,
            MatchResult.filters_key == key,
            MatchResult.created_at >= now - max_age,
        )
        .order_by(MatchResult.created_at.desc())
        .limit(1)
    )
    if row is None:
        return None
    result = MatchesOut.model_validate(row.payload)
    # Jobs close between ingestion runs; don't show ones that have.
    ids = [m.job.id for m in result.matches]
    active = set(await session.scalars(select(Job.id).where(Job.id.in_(ids), Job.is_active)))
    result.matches = [m for m in result.matches if m.job.id in active]
    result.cached = True
    return result


async def find_matches(
    session: AsyncSession,
    resume: Resume,
    *,
    llm: LLMClient,
    embedder: Embedder,
    settings: Settings,
    filters: MatchFilters,
    refresh: bool = False,
    store: bool = True,  # False for experiments that shouldn't replace what users see
    now: datetime | None = None,
) -> MatchesOut:
    now = now or datetime.now(UTC)
    key = filters.cache_key()
    lock = _lock_for(f"{resume.id}|{key}")
    async with lock:
        if not refresh:
            hit = await _cached(
                session, resume.id, key, timedelta(hours=settings.match_cache_hours), now
            )
            if hit is not None:
                return hit
        return await _compute(
            session, resume, llm=llm, embedder=embedder, settings=settings,
            filters=filters, key=key, store=store, now=now,
        )  # fmt: skip


async def _compute(
    session: AsyncSession,
    resume: Resume,
    *,
    llm: LLMClient,
    embedder: Embedder,
    settings: Settings,
    filters: MatchFilters,
    key: str,
    store: bool,
    now: datetime,
) -> MatchesOut:
    started = time.perf_counter()
    profile = ResumeProfile.model_validate(resume.parsed)
    vector, embed_model = resume.embedding, resume.embed_model
    if vector is None or embed_model != embedder.model_name:
        vector = await embedder.embed_query(embedding_text(profile))
        embed_model = embedder.model_name

    candidates = await retrieve(
        session, list(vector), embed_model=embed_model, filters=filters,
        limit=settings.match_candidates, now=now,
    )  # fmt: skip
    retrieved = time.perf_counter()

    jobs = {c.job.id: c.job for c in candidates}
    scored = score_candidates(
        [(c.job.id, c.similarity, c.job.skills, c.job.seniority) for c in candidates],
        profile.skills,
        profile.seniority,
    )
    top = _unique_postings(scored, jobs)[: settings.match_rerank_top]
    scored_at = time.perf_counter()

    judgements: dict[int, rerank.Judgement] = {}
    note, model, tokens = None, None, None
    if top:
        cards = [
            rerank.JobCard(
                number=i, title=jobs[s.job_id].title, company=jobs[s.job_id].company,
                seniority=jobs[s.job_id].seniority, skills=jobs[s.job_id].skills,
                description=jobs[s.job_id].description,
            )
            for i, s in enumerate(top, start=1)
        ]  # fmt: skip
        try:
            result = await llm.structured_detailed(
                rerank.build_prompt(profile, cards),
                rerank.RerankResult,
                system=rerank.SYSTEM_PROMPT,
                fast=settings.match_rerank_fast,
                reasoning_effort=settings.match_reasoning_effort,
            )
            judgements = rerank.merge(result.value, len(cards))
            model = result.model
            if result.prompt_tokens is not None:
                tokens = result.prompt_tokens + (result.completion_tokens or 0)
        except LLMError as exc:
            log.warning("re-rank failed, returning stage-2 ranking: %s", exc)
            note = RATE_LIMITED_NOTE if "HTTP 429" in str(exc) else UNAVAILABLE_NOTE
    reranked_at = time.perf_counter()

    matches = []
    for number, s in enumerate(top, start=1):
        job = jobs[s.job_id]
        judged = judgements.get(number)
        matches.append(
            MatchOut(
                job=JobOut(
                    id=job.id, title=job.title, company=job.company, location=job.location,
                    url=job.url, source=job.source, salary=job.salary,
                    seniority=job.seniority, posted_at=job.posted_at,
                ),
                score=judged.score if judged else round(s.hybrid * 100),
                reason=judged.reason if judged else rule_reason(s, len(job.skills)),
                matched_skills=s.matched[:8],
                missing_skills=clean_missing(
                    judged.missing_skills if judged else [], job.skills, profile.skills
                )
                or s.missing[:4],
                similarity=round(s.similarity, 4),
                hybrid=round(s.hybrid, 4),
                llm_score=judged.score if judged else None,
            )
        )  # fmt: skip
    # Judged jobs by the LLM's score; any it skipped keep their stage-2 order after them.
    matches.sort(key=lambda m: (m.llm_score is not None, m.llm_score or 0, m.hybrid), reverse=True)

    out = MatchesOut(
        resume_id=resume.id,
        generated_at=now,
        cached=False,
        reranked=bool(judgements),
        model=model,
        note=note,
        candidates=len(candidates),
        filters=filters,
        timings=Timings(
            retrieve_ms=_ms(retrieved - started),
            score_ms=_ms(scored_at - retrieved),
            rerank_ms=_ms(reranked_at - scored_at),
            total_ms=_ms(reranked_at - started),
        ),
        tokens=tokens,
        matches=matches,
    )
    if store and (out.reranked or not top):
        session.add(
            MatchResult(resume_id=resume.id, filters_key=key, payload=out.model_dump(mode="json"))
        )
        await session.commit()
    return out
