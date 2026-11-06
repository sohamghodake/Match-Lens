"""Stage 3: one LLM call scores the top candidates 0-100 with a reason each.

Sized for Groq's free tier (8,000 tokens per minute, hidden reasoning included): each
job is a compact card, not its full description, and reasoning effort is set to low.
"""

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.parsing.schema import ResumeProfile
from app.parsing.skills import normalize_skills

MAX_JOB_SKILLS = 12
SNIPPET_CHARS = 280
MAX_REASON_CHARS = 220

SYSTEM_PROMPT = "You are a careful technical recruiter matching one candidate to job openings."

PROMPT = """\
Score how well each job fits this candidate, from 0 to 100:
90+ strong fit, could apply today; 70-89 good fit with small gaps; 40-69 partial fit; \
below 40 poor fit. Weigh skills, level of experience and domain. A job far above the \
candidate's level is a poor fit even if the skills match. A job far below the \
candidate's skills (data labeling, annotation, content review, generic AI-training \
gigs) is also a weak fit, even if it has no requirements.

For each job give a one-sentence reason (at most 25 words) naming concrete skills or \
experience, and up to 4 important skills the candidate is missing. Score every job \
exactly once, using its number.

Candidate:
{candidate}

Jobs:
{jobs}"""

# Where the useful part of a description usually starts; the opening paragraphs are
# often company boilerplate ("At Acme, we believe...").
_REQUIREMENTS = re.compile(
    r"(what you.?ll (do|need|bring)|requirements|qualifications|about you|you have|"
    r"you will|responsibilities|who you are|what we.?re looking for)",
    re.I,
)


class RankedJob(BaseModel):
    job: int
    score: int = Field(ge=0, le=100)
    reason: str
    missing_skills: list[str] = Field(default_factory=list)


class RerankResult(BaseModel):
    jobs: list[RankedJob]


@dataclass
class JobCard:
    number: int  # 1-based position in the prompt
    title: str
    company: str
    seniority: str | None
    skills: list[str]
    description: str


def snippet(description: str, limit: int = SNIPPET_CHARS) -> str:
    match = _REQUIREMENTS.search(description)
    text = description[match.start() :] if match else description
    text = " ".join(text.split())
    return text[:limit].rsplit(" ", 1)[0] + "…" if len(text) > limit else text


def candidate_summary(profile: ResumeProfile) -> str:
    years = f"{profile.total_years_experience:g} years of professional experience"
    lines = [
        f"Headline: {profile.headline or 'n/a'}",
        f"Level: {profile.seniority}, {years}",
        f"Skills: {', '.join(profile.skills[:30]) or 'none listed'}",
    ]
    if profile.roles:
        roles = "; ".join(
            f"{r.title} at {r.company} ({r.start or '?'} to {r.end or '?'})"
            for r in profile.roles[:5]
        )
        lines.append(f"Experience: {roles}")
    if profile.projects:
        projects = "; ".join(
            f"{p.name}" + (f": {p.summary}" if p.summary else "")
            + (f" [{', '.join(p.skills[:6])}]" if p.skills else "")
            for p in profile.projects[:4]
        )  # fmt: skip
        lines.append(f"Projects: {projects}")
    if profile.education:
        e = profile.education[0]
        lines.append(
            "Education: " + ", ".join(x for x in (e.degree, e.field, e.institution, e.end) if x)
        )
    return "\n".join(lines)


def job_card_text(card: JobCard) -> str:
    level = f" ({card.seniority})" if card.seniority else ""
    skills = ", ".join(card.skills[:MAX_JOB_SKILLS]) or "none listed"
    return (
        f"[{card.number}] {card.title}{level} at {card.company}\n"
        f"    Skills: {skills}\n"
        f"    {snippet(card.description)}"
    )


def build_prompt(profile: ResumeProfile, cards: list[JobCard]) -> str:
    return PROMPT.format(
        candidate=candidate_summary(profile),
        jobs="\n".join(job_card_text(c) for c in cards),
    )


@dataclass
class Judgement:
    score: int
    reason: str
    missing_skills: list[str]


def merge(result: RerankResult, count: int) -> dict[int, Judgement]:
    """Card number -> judgement. Ignores numbers out of range and repeats (first wins);
    jobs the model skipped are simply absent and keep their stage-2 score."""
    judged: dict[int, Judgement] = {}
    for item in result.jobs:
        if 1 <= item.job <= count and item.job not in judged:
            reason = " ".join(item.reason.split())
            if len(reason) > MAX_REASON_CHARS:
                reason = reason[:MAX_REASON_CHARS].rsplit(" ", 1)[0] + "…"
            judged[item.job] = Judgement(
                score=item.score,
                reason=reason,
                missing_skills=normalize_skills(item.missing_skills)[:4],
            )
    return judged
