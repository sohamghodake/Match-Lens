"""Optional LLM pass over job descriptions, on top of the free dictionary scan.

Measured on 8 real jobs with qwen2.5:3b on CPU (6 Nov 2026): ~14 s per job, and 6 of
its 10 additions were not in the text. So it is off by default, and any skill the model
adds is kept only if the description actually mentions it.

Off by default (INGEST_LLM_SKILLS=false): the dictionary scan is free, instant and
runs anywhere, including GitHub Actions. When enabled it is meant for a local model
(free), one job per call because small models have small context windows, and capped
per run so a backfill of thousands of jobs can't run for hours.
"""

import logging
import re
import time
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.llm.client import LLMClient, LLMError
from app.parsing.skills import CANONICAL_SKILLS, normalize_skills
from ingestion.normalize import NormalizedJob

log = logging.getLogger(__name__)

MAX_DESCRIPTION_CHARS = 3000

PROMPT = """\
Read the job description and list the technical skills it mentions by name: \
programming languages, frameworks, libraries, databases, cloud platforms and tools. \
Only include names that literally appear in the text. Do not invent skills and do not \
return category words. Put must-haves in "required" and preferred skills in \
"nice_to_have".

Example answer: {{"required": ["Python", "PostgreSQL", "AWS"], "nice_to_have": ["Kubernetes"]}}

Job title: {title}
Description:
<<<
{description}
>>>"""


def mentioned_in(skill: str, text: str) -> bool:
    """Does the text name this skill (or one of its aliases)? Guards against invented skills."""
    names = (skill, *CANONICAL_SKILLS.get(skill, ()))
    return any(re.search(rf"(?<![\w.+#-]){re.escape(n)}(?![\w+#])", text, re.I) for n in names if n)


class JobSkills(BaseModel):
    required: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)


@dataclass
class EnrichStats:
    attempted: int = 0
    failed: int = 0
    seconds: float = 0.0
    added: int = 0  # skills the dictionary scan had missed, found in the text
    rejected: int = 0  # model suggestions not mentioned in the description
    skipped_over_cap: int = 0
    errors: list[str] = field(default_factory=list)


async def enrich_skills(jobs: list[NormalizedJob], llm: LLMClient, *, max_jobs: int) -> EnrichStats:
    stats = EnrichStats(skipped_over_cap=max(0, len(jobs) - max_jobs))
    for job in jobs[:max_jobs]:
        stats.attempted += 1
        prompt = PROMPT.format(title=job.title, description=job.description[:MAX_DESCRIPTION_CHARS])
        started = time.perf_counter()
        try:
            result = await llm.structured(prompt, JobSkills, fast=True)
        except LLMError as exc:
            stats.failed += 1
            stats.errors.append(str(exc)[:200])
            continue
        finally:
            stats.seconds += time.perf_counter() - started
        known = {s.lower() for s in job.skills}
        text = f"{job.title}\n{job.description}"
        suggested = normalize_skills([*result.required, *result.nice_to_have])
        new = [s for s in suggested if s.lower() not in known]
        kept = [s for s in new if mentioned_in(s, text)]
        stats.added += len(kept)
        stats.rejected += len(new) - len(kept)
        job.skills = [*job.skills, *kept]
    return stats
