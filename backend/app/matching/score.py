"""Stage 2: blend vector similarity, skill coverage and seniority fit into one score.

Pure functions, so the weights can be tuned against labeled relevance in Phase 6.
"""

from dataclasses import dataclass

from app.parsing.schema import SENIORITY_LEVELS

# Starting weights; Phase 6 measures precision@10 to tune them.
SIMILARITY_WEIGHT = 0.55
SKILLS_WEIGHT = 0.45
UNKNOWN_SKILLS_COVERAGE = 0.5  # job lists no recognizable skills: neither reward nor punish

LEVEL = {level: i for i, level in enumerate(SENIORITY_LEVELS)}  # intern 0 ... lead 4


@dataclass
class Scored:
    job_id: int
    similarity: float  # raw cosine similarity, 0..1
    similarity_norm: float  # min-max scaled within this candidate set
    coverage: float  # share of the job's skills the candidate has
    matched: list[str]
    missing: list[str]
    penalty: float
    hybrid: float  # the stage-2 score, 0..1


def skill_overlap(job_skills: list[str], resume_skills: list[str]) -> tuple[list[str], list[str]]:
    """(skills the candidate has, skills they lack), in the job's own order."""
    have = {s.lower() for s in resume_skills}
    matched = [s for s in job_skills if s.lower() in have]
    missing = [s for s in job_skills if s.lower() not in have]
    return matched, missing


def seniority_penalty(resume_level: str | None, job_level: str | None) -> float:
    """Jobs well above the candidate's level are mostly out of reach; well below is a
    weaker fit. Jobs whose title states no level ("Software Engineer") are not penalized."""
    if resume_level not in LEVEL or job_level not in LEVEL:
        return 0.0
    gap = LEVEL[job_level] - LEVEL[resume_level]
    if gap >= 2:
        return 0.25
    if gap == 1:
        return 0.08
    if gap <= -2:
        return 0.10
    return 0.0


def score_candidates(
    candidates: list[tuple[int, float, list[str], str | None]],
    resume_skills: list[str],
    resume_level: str | None,
) -> list[Scored]:
    """candidates: (job_id, cosine similarity, job skills, job seniority). Best first."""
    if not candidates:
        return []
    sims = [c[1] for c in candidates]
    low, high = min(sims), max(sims)
    spread = high - low

    scored = []
    for job_id, similarity, job_skills, job_level in candidates:
        norm = (similarity - low) / spread if spread > 1e-9 else 1.0
        matched, missing = skill_overlap(job_skills, resume_skills)
        coverage = len(matched) / len(job_skills) if job_skills else UNKNOWN_SKILLS_COVERAGE
        penalty = seniority_penalty(resume_level, job_level)
        hybrid = SIMILARITY_WEIGHT * norm + SKILLS_WEIGHT * coverage - penalty
        scored.append(
            Scored(
                job_id=job_id,
                similarity=similarity,
                similarity_norm=norm,
                coverage=coverage,
                matched=matched,
                missing=missing,
                penalty=penalty,
                hybrid=max(0.0, min(1.0, hybrid)),
            )
        )
    scored.sort(key=lambda s: (s.hybrid, s.similarity), reverse=True)
    return scored


def rule_reason(s: Scored, total_job_skills: int) -> str:
    """A one-line explanation when no LLM reason is available."""
    if s.matched and total_job_skills:
        shown = ", ".join(s.matched[:4])
        more = f" and {len(s.matched) - 4} more" if len(s.matched) > 4 else ""
        reason = (
            f"You have {len(s.matched)} of its {total_job_skills} listed skills: {shown}{more}."
        )
    else:
        reason = "Similar to your experience, though it lists few skills we recognize."
    if s.penalty >= 0.25:
        reason += " It's pitched well above your current level."
    return reason
