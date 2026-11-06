"""Read a job description: title, level, years required, and its keywords.

One LLM call extracts keywords in the posting's own wording (ATS match words, so
"Postgres" stays "Postgres"). Anything the posting doesn't actually contain is dropped,
the dictionary scan adds skills the model missed, and if the LLM is unavailable the
dictionary and regexes do the whole job.
"""

import hashlib
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app.llm.client import LLMClient, LLMError
from app.parsing.schema import Seniority
from app.parsing.seniority import seniority_from_title
from app.parsing.skills import CANONICAL_SKILLS, find_known_skills, normalize_skill
from ingestion.llm_skills import mentioned_in

log = logging.getLogger(__name__)

MAX_REQUIRED, MAX_PREFERRED = 15, 10
MAX_DESCRIPTION_CHARS = 12_000

PROMPT = """\
Analyze this job posting for an ATS keyword check.

- title: the job title.
- seniority: intern, junior, mid, senior or lead, or null if the posting doesn't say.
- min_years: the minimum years of experience it asks for, or null.
- required: technical skills it requires: languages, frameworks, databases, tools, \
platforms, methods and certifications.
- preferred: technical skills it lists as preferred, nice to have, or a bonus.

Not activities ("hackathons"), generic phrases ("personal projects", "AI tools") or \
soft skills.

Use the posting's exact wording for each keyword (if it says "Postgres", write \
"Postgres"). Keywords are 1-3 words. At most {max_required} required and \
{max_preferred} preferred.

Posting:
<<<
{text}
>>>"""


class JDAnalysis(BaseModel):
    title: str | None = None
    seniority: Seniority | None = None
    min_years: float | None = Field(None, ge=0, le=40)
    required: list[str] = Field(default_factory=list)
    preferred: list[str] = Field(default_factory=list)


@dataclass
class JobDescription:
    title: str | None
    seniority: str | None
    min_years: float | None
    required: list[str] = field(default_factory=list)
    preferred: list[str] = field(default_factory=list)
    method: Literal["llm", "rules"] = "rules"


_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years?|yrs?)\b", re.I)


def min_years_from_text(text: str) -> float | None:
    """The smallest "N+ years" that reads like an experience requirement."""
    found = [
        float(m.group(1))
        for m in _YEARS.finditer(text)
        if re.search(r"experience|professional|industry", text[m.end() : m.end() + 60], re.I)
    ]
    return min(found) if found else None


# Generic phrases a model sometimes returns as "keywords"; kept only if a known skill.
_GENERIC = re.compile(
    r"\b(projects?|experience|challenges?|hackathons?|tools?|skills?|teamwork|degree|"
    r"portfolio|mindset|ability|knowledge|understanding|passion|background)\b",
    re.I,
)


def _is_known(keyword: str) -> bool:
    return normalize_skill(keyword) in CANONICAL_SKILLS


def _split_combined(keyword: str) -> list[str]:
    """ "JavaScript/TypeScript" -> both, when each part is a known skill ("CI/CD" stays)."""
    if _is_known(keyword) or "/" not in keyword:
        return [keyword]
    parts = [p.strip() for p in keyword.split("/")]
    return parts if all(_is_known(p) for p in parts) else [keyword]


def _dedupe(keywords: list[str], seen: set[str]) -> list[str]:
    out = []
    for k in (part for keyword in keywords for part in _split_combined(keyword)):
        if _GENERIC.search(k) and not _is_known(k):
            continue
        k = " ".join(k.split()).strip(" .,;")
        key = (normalize_skill(k) or k).lower()
        if k and key not in seen and len(k) <= 40:
            seen.add(key)
            out.append(k)
    return out


def analyze_with_rules(text: str) -> JobDescription:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    title = first_line[:120] if len(first_line.split()) <= 12 else None
    seen: set[str] = set()
    return JobDescription(
        title=title,
        seniority=seniority_from_title(title or ""),
        min_years=min_years_from_text(text),
        required=_dedupe(find_known_skills(text), seen)[: MAX_REQUIRED + MAX_PREFERRED],
        method="rules",
    )


# The same posting must always score the same: the model's keyword list varies a little
# between calls, so each posting's analysis is cached (and the tokens saved). Rule-based
# results aren't cached, so the next request retries the model.
_CACHE: "OrderedDict[str, JobDescription]" = OrderedDict()
CACHE_SIZE = 512


async def analyze(text: str, llm: LLMClient) -> JobDescription:
    text = text[:MAX_DESCRIPTION_CHARS]
    key = hashlib.sha256(" ".join(text.split()).encode()).hexdigest()
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    result = await _analyze(text, llm)
    if result.method == "llm":
        _CACHE[key] = result
        if len(_CACHE) > CACHE_SIZE:
            _CACHE.popitem(last=False)
    return result


async def _analyze(text: str, llm: LLMClient) -> JobDescription:
    try:
        raw = await llm.structured(
            PROMPT.format(text=text, max_required=MAX_REQUIRED, max_preferred=MAX_PREFERRED),
            JDAnalysis,
            reasoning_effort="low",
        )
    except LLMError as exc:
        log.warning("job description analysis fell back to rules: %s", exc)
        return analyze_with_rules(text)

    seen: set[str] = set()
    # Only keywords the posting really contains (in its wording or a known alias).
    required = _dedupe([k for k in raw.required if mentioned_in(k, text)], seen)
    preferred = _dedupe([k for k in raw.preferred if mentioned_in(k, text)], seen)
    # Skills the dictionary finds but the model didn't list count as preferred.
    preferred += _dedupe(find_known_skills(text), seen)
    return JobDescription(
        title=(raw.title or "").strip() or None,
        seniority=raw.seniority or seniority_from_title(raw.title or ""),
        min_years=raw.min_years if raw.min_years is not None else min_years_from_text(text),
        required=required[:MAX_REQUIRED],
        preferred=preferred[:MAX_PREFERRED],
        method="llm",
    )
