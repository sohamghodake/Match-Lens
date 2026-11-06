"""Resume text -> ResumeProfile. LLM first; rule-based fallback when the LLM fails.

The LLM only extracts (titles, companies, dates as written, skills). Code then
normalizes dates and skills and computes total experience, which keeps the numbers
deterministic and testable.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from app.llm.client import LLMClient, LLMError
from app.parsing.dates import (
    PRESENT,
    YearMonth,
    find_date_ranges,
    normalize_date,
    parse_date,
    total_years,
)
from app.parsing.schema import Education, LLMResume, ResumeProfile, Role
from app.parsing.seniority import infer_seniority, is_internship, seniority_from_title
from app.parsing.skills import find_known_skills, normalize_skills

log = logging.getLogger(__name__)

MAX_LLM_CHARS = 16_000  # ~4k tokens; real resumes are well under this

SYSTEM_PROMPT = "You extract structured data from resumes for a job-matching service."

USER_PROMPT = """\
Extract the candidate's profile from the resume below.

Rules:
- roles: every job, internship, freelance or contract position, most recent first. \
List a promotion at the same company as a separate role. Leave out education, \
volunteering and personal projects unless they are presented as a job.
- For each role, copy the title and the company name exactly as written; put any city \
or "Remote" in location, not in company. Copy the start and end dates exactly as \
written (e.g. "Mar 2021", "03/2021", "2019"). Use "Present" for a current role. Use \
null only when the resume gives no date at all.
- skills: technical skills, programming languages, frameworks, tools, platforms and \
methods mentioned anywhere (skills section and experience bullets). One skill per item, \
short names, no soft skills, no duplicates.
- education: institution, degree, field and graduation year.
- headline: the candidate's current title, or their stated target title.
- seniority: intern, junior, mid, senior or lead, judged from titles and \
responsibilities; lead covers staff, principal, architect and engineering management.
- total_years_experience: professional experience in years, excluding internships.

Contact details have been replaced with [email] and [phone].

Resume:
<<<
{text}
>>>"""

FALLBACK_WARNING = (
    "The AI parser was unavailable, so this profile was built with simple rules; "
    "individual roles aren't listed."
)


@dataclass
class ParsedResume:
    profile: ResumeProfile
    method: Literal["llm", "fallback"]
    warnings: list[str] = field(default_factory=list)


async def parse_resume(text: str, llm: LLMClient, *, today: date | None = None) -> ParsedResume:
    today = today or date.today()
    prompt = USER_PROMPT.format(text=text[:MAX_LLM_CHARS])
    try:
        raw = await llm.structured(prompt, LLMResume, system=SYSTEM_PROMPT)
    except LLMError as exc:
        log.warning("resume parse fell back to rules: %s", exc)
        return parse_with_rules(text, today=today)
    profile, warnings = build_profile(raw, today=today, text=text)
    return ParsedResume(profile=profile, method="llm", warnings=warnings)


def build_profile(
    raw: LLMResume, *, today: date, text: str = ""
) -> tuple[ResumeProfile, list[str]]:
    warnings: list[str] = []
    roles: list[Role] = []
    lines = text.splitlines()
    used_lines: set[int] = set()
    for item in raw.roles:
        title, company = item.title.strip(), item.company.strip()
        if not title and not company:
            continue
        start, end = normalize_date(item.start), normalize_date(item.end)
        if (start is None or end is None) and lines:
            # Small models often drop dates they were shown; take them from the text.
            found = _dates_near_role(title, company, lines, used_lines)
            if found:
                start = start or normalize_date(found[0])
                end = end or normalize_date(found[1])
        label = f"{title or 'Role'} at {company or 'unknown company'}"
        if start is None:
            unreadable = f' ("{item.start}")' if item.start else ""
            warnings.append(f"No start date found for {label}{unreadable}.")
        if end is None:
            unreadable = f' ("{item.end}")' if item.end else ""
            warnings.append(f"No end date found for {label}{unreadable}.")
        location = (item.location or "").strip() or None
        roles.append(Role(title=title, company=company, location=location, start=start, end=end))
    roles.sort(key=lambda r: _recency(r, today), reverse=True)

    professional = [r for r in roles if not is_internship(r.title)]
    computed = total_years([(r.start, r.end) for r in professional], today)
    has_dates = any(r.start for r in professional)
    years = computed if has_dates else (raw.total_years_experience or 0.0)

    if not roles:
        warnings.append("No work experience was found.")

    education = [
        Education(
            institution=e.institution.strip(),
            degree=(e.degree or "").strip() or None,
            field=(e.field or "").strip() or None,
            end=_year(e.end),
        )
        for e in raw.education
        if e.institution.strip()
    ]
    profile = ResumeProfile(
        headline=(raw.headline or "").strip() or (roles[0].title if roles else None),
        # An explicit level in the latest title ("Senior ...", "Staff ...") beats the
        # model's judgment; small models in particular over-rate seniority.
        seniority=(seniority_from_title(roles[0].title) if roles else None) or raw.seniority,
        total_years_experience=years,
        skills=normalize_skills(raw.skills),
        roles=roles,
        education=education,
    )
    return profile, warnings


def parse_with_rules(text: str, *, today: date | None = None) -> ParsedResume:
    """Fallback when the LLM is down or returns garbage twice."""
    today = today or date.today()
    experience = _section(text, EXPERIENCE_HEADINGS) or _without_education_lines(text)
    ranges = _professional_ranges(experience)
    latest_title = _line_with_first_range(experience)
    only_internships = bool(latest_title) and is_internship(latest_title or "")
    years = 0.0 if only_internships else total_years(ranges, today)
    profile = ResumeProfile(
        headline=None,
        seniority=infer_seniority(latest_title, years, only_internships=only_internships),
        total_years_experience=years,
        skills=find_known_skills(text),
        roles=[],
        education=[],
    )
    return ParsedResume(profile=profile, method="fallback", warnings=[FALLBACK_WARNING])


def embedding_text(profile: ResumeProfile) -> str:
    """A compact summary to embed. The raw resume would be cut off at the embedding
    model's 512-token limit, losing most of the work history."""
    parts = []
    if profile.headline:
        parts.append(profile.headline)
    parts.append(f"{profile.seniority} level, {profile.total_years_experience:g} years")
    if profile.skills:
        parts.append("Skills: " + ", ".join(profile.skills[:40]))
    if profile.roles:
        parts.append(
            "Experience: " + "; ".join(f"{r.title} at {r.company}" for r in profile.roles[:8])
        )
    return ". ".join(parts)


# ── helpers ───────────────────────────────────────────────────────────────────────


def _recency(role: Role, today: date) -> tuple[int, int]:
    def index(value: str | None) -> int:
        parsed = parse_date(value)
        if parsed == PRESENT:
            return today.year * 12 + today.month
        if isinstance(parsed, YearMonth):
            return parsed.year * 12 + (parsed.month or 6)
        return -1

    end = index(role.end)
    start = index(role.start)
    return (end if end >= 0 else start, start)


_LEVEL_SUFFIX = r"(?!\s+(?:I{1,3}|IV|V|VI|\d+)\b)"  # "Engineer" must not match "Engineer II"


def _dates_near_role(
    title: str, company: str, lines: list[str], used: set[int]
) -> tuple[str, str] | None:
    """The date range printed with this role: on the title's line, the line after it
    (dates under the title), or the line before. Each line is used for one role only."""
    if not title:
        return None
    pattern = re.compile(rf"(?<!\w){re.escape(title)}(?!\w){_LEVEL_SUFFIX}", re.I)
    candidates = [i for i, line in enumerate(lines) if i not in used and pattern.search(line)]
    if company:
        nearby = [i for i in candidates if company.lower() in " ".join(lines[i : i + 2]).lower()]
        candidates = nearby or candidates
    for i in candidates:
        for j in (i, i + 1, i - 1):
            if 0 <= j < len(lines) and (ranges := find_date_ranges(lines[j])):
                used.add(i)
                return ranges[0]
    return None


def _year(value: str | None) -> str | None:
    parsed = parse_date(value)
    return str(parsed.year) if isinstance(parsed, YearMonth) else None


EXPERIENCE_HEADINGS = re.compile(
    r"^\s*(work |professional |relevant )?(experience|employment( history)?|work history|career)"
    r"\s*:?\s*$",
    re.I | re.M,
)
OTHER_HEADINGS = re.compile(
    r"^\s*(education|skills|technical skills|projects|certifications?|awards|publications|"
    r"languages|interests|volunteer(ing)?|summary|profile)\s*:?\s*$",
    re.I | re.M,
)
EDUCATION_WORDS = re.compile(
    r"\b(university|college|institute|school|bachelor|master|b\.?s\.?c?|m\.?s\.?c?|b\.?tech|"
    r"m\.?tech|b\.?e\.?|ph\.?d|mba|degree|gpa|cgpa)\b",
    re.I,
)


def _section(text: str, heading: re.Pattern[str]) -> str | None:
    match = heading.search(text)
    if not match:
        return None
    rest = text[match.end() :]
    following = OTHER_HEADINGS.search(rest)
    return rest[: following.start()] if following else rest


def _without_education_lines(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not EDUCATION_WORDS.search(line))


def _professional_ranges(text: str) -> list[tuple[str, str]]:
    """Date ranges in the experience text, skipping internships (a title on the same
    line or the line above), which don't count toward years of experience."""
    lines = text.splitlines()
    ranges = []
    for i, line in enumerate(lines):
        context = f"{lines[i - 1] if i else ''} {line}"
        if not is_internship(context):
            ranges += find_date_ranges(line)
    return ranges


def _line_with_first_range(text: str) -> str | None:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if find_date_ranges(line):
            # Titles sit on the date line or the line just above it.
            for candidate in (line, lines[i - 1] if i else ""):
                if seniority_from_title(candidate):
                    return candidate
            return line
    return None
