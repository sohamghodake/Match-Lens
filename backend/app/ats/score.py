"""ATS score = 100 minus explained deductions, in four parts.

Pure functions: every deduction is created with its points, reason and fix, and a part's
points are its maximum minus its deductions, so nothing can be lost silently.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.ats.schema import Deduction, KeywordResult, Note, ScorePart
from app.matching.score import LEVEL
from app.parsing.skills import normalize_skill, search_names

KEYWORDS_MAX = 40.0
SECTIONS_MAX = 20.0
FORMATTING_MAX = 20.0
SENIORITY_MAX = 20.0
REQUIRED_WEIGHT, PREFERRED_WEIGHT = 2.0, 1.0


def _part(
    key: str,
    name: str,
    max_points: float,
    deductions: list[Deduction],
    notes: Sequence[Note] = (),
) -> ScorePart:
    deductions = [d for d in deductions if d.points > 0]
    # Per-item rounding can overshoot the part's maximum by a tenth; trim the last item
    # so the deductions always add up to exactly what was lost.
    excess = round(sum(d.points for d in deductions) - max_points, 1)
    if excess > 0:
        deductions[-1].points = round(deductions[-1].points - excess, 1)
    lost = round(sum(d.points for d in deductions), 1)
    return ScorePart(
        key=key,  # type: ignore[arg-type]
        name=name,
        max_points=max_points,
        points=round(max_points - lost, 1),
        deductions=deductions,
        notes=list(notes),
    )


def _find(term: str, text: str) -> str | None:
    """The text as written in the resume, if it mentions the term."""
    match = re.search(rf"(?<![\w.+#-]){re.escape(term)}(?![\w+#])", text, re.I)
    return match.group(0) if match else None


# ── keywords ──────────────────────────────────────────────────────────────────────


def match_keyword(keyword: str, resume_text: str, resume_skills: list[str]) -> KeywordResult:
    """Exact wording first; then any synonym (alias) of the same skill."""
    if _find(keyword, resume_text):
        return KeywordResult(keyword=keyword, importance="required", status="found")
    canonical = normalize_skill(keyword) or keyword
    for name in search_names(canonical):
        written = _find(name, resume_text) if name.lower() != keyword.lower() else None
        if written:
            return KeywordResult(
                keyword=keyword, importance="required", status="synonym", resume_term=written
            )
    if canonical.lower() in {s.lower() for s in resume_skills}:
        return KeywordResult(
            keyword=keyword, importance="required", status="synonym", resume_term=canonical
        )
    return KeywordResult(keyword=keyword, importance="required", status="missing")


def score_keywords(
    required: list[str], preferred: list[str], resume_text: str, resume_skills: list[str]
) -> tuple[ScorePart, list[KeywordResult]]:
    results: list[KeywordResult] = []
    for importance, keywords in (("required", required), ("preferred", preferred)):
        for keyword in keywords:
            result = match_keyword(keyword, resume_text, resume_skills)
            result.importance = importance  # type: ignore[assignment]
            results.append(result)

    total_weight = sum(
        REQUIRED_WEIGHT if r.importance == "required" else PREFERRED_WEIGHT for r in results
    )
    deductions, notes = [], []
    for r in results:
        weight = REQUIRED_WEIGHT if r.importance == "required" else PREFERRED_WEIGHT
        if r.status == "missing":
            deductions.append(
                Deduction(
                    points=round(KEYWORDS_MAX * weight / total_weight, 1),
                    reason=f'{r.importance.capitalize()} keyword "{r.keyword}" is not in '
                    "your resume.",
                    suggestion=f"If you have used {r.keyword}, name it in a role or project "
                    "where you used it.",
                )
            )
        elif r.status == "synonym":
            notes.append(
                Note(
                    message=(
                        f'The posting says "{r.keyword}" and your resume says "{r.resume_term}". '
                        "Some ATS only match exact words; consider using the posting's wording too."
                    )
                )
            )
    if deductions:
        # Per-keyword rounding shouldn't leave a tenth of a point behind (or take one
        # extra): the deductions add up to exactly the weighted share of what's missing.
        missing_weight = sum(
            REQUIRED_WEIGHT if r.importance == "required" else PREFERRED_WEIGHT
            for r in results
            if r.status == "missing"
        )
        target = round(KEYWORDS_MAX * missing_weight / total_weight, 1)
        drift = round(target - sum(d.points for d in deductions), 1)
        deductions[-1].points = round(deductions[-1].points + drift, 1)
    if not results:
        notes.append(Note(message="No recognizable skills or tools found in this posting."))
    return _part("keywords", "Keyword coverage", KEYWORDS_MAX, deductions, notes), results


# ── sections and contact details ──────────────────────────────────────────────────

_HEADINGS = {
    "experience": r"(work |professional |relevant )?experience|employment( history)?|work history",
    "education": r"education|academic background|qualifications",
    "skills": r"(technical |core |key )?skills|technologies|tech stack|core competencies",
    "projects": r"(personal |academic |selected |key )?projects",
    "summary": r"summary|profile|about me|objective",
}


def find_sections(text: str) -> set[str]:
    """Section headings: short lines that are just a heading ("Technical Skills")."""
    found = set()
    for line in text.splitlines():
        clean = line.strip().strip(":").strip()
        if not clean or len(clean.split()) > 4:
            continue
        for name, pattern in _HEADINGS.items():
            if re.fullmatch(pattern, clean, re.I):
                found.add(name)
    return found


# (points, reason, fix) for each missing piece.
MISSING_EMAIL = (3, "No email address found.", "Put your email in the header, as plain text.")
MISSING_PHONE = (2, "No phone number found.", "Add a phone number in the header.")
MISSING_SECTION = {
    "experience": (6, 'No "Experience" section heading found.',
                   'Use a standard heading such as "Experience".'),
    "education": (4, 'No "Education" section heading found.',
                  'Add an "Education" section with your degree and year.'),
    "skills": (5, 'No "Skills" section heading found.',
               'Add a "Skills" section that lists tools by name.'),
}  # fmt: skip
PROJECTS_INSTEAD = (3, 'No "Experience" section; your projects carry the weight instead.',
                    'Add internships or freelance work under an "Experience" heading.')  # fmt: skip


def _deduct(rule: tuple[float, str, str]) -> Deduction:
    points, reason, suggestion = rule
    return Deduction(points=points, reason=reason, suggestion=suggestion)


def score_sections(text: str, meta_file: dict, has_location: bool) -> ScorePart:
    sections = find_sections(text)
    deductions = []
    if not meta_file.get("has_email"):
        deductions.append(_deduct(MISSING_EMAIL))
    if not meta_file.get("has_phone"):
        deductions.append(_deduct(MISSING_PHONE))
    for name, rule in MISSING_SECTION.items():
        if name not in sections:
            use_projects = name == "experience" and "projects" in sections
            deductions.append(_deduct(PROJECTS_INSTEAD if use_projects else rule))
    notes = []
    if not has_location:
        notes.append(
            Note(
                message="No city or country found. Recruiters often filter by location; "
                "add one to your header."
            )
        )
    return _part("sections", "Sections and contact details", SECTIONS_MAX, deductions, notes)


# ── formatting ────────────────────────────────────────────────────────────────────

SHORT_CHARS = 1_200  # under this the resume reads as thin
LONG_CHARS = 9_000  # about three dense pages


def score_formatting(meta_file: dict) -> ScorePart:
    deductions = []
    if meta_file.get("columns", 1) > 1:
        deductions.append(
            Deduction(
                points=8,
                reason="Two-column layout.",
                suggestion="Many ATS read straight across the page and mix the columns; "
                "use a single column.",
            )
        )
    if meta_file.get("tables", 0) > 0:
        deductions.append(
            Deduction(
                points=5,
                reason=f"{meta_file['tables']} table(s) in the file.",
                suggestion="Some ATS skip or scramble tables; use plain text and bullets.",
            )
        )
    pages, chars = meta_file.get("pages"), meta_file.get("chars", 0)
    if (pages and pages > 2) or chars > LONG_CHARS:
        deductions.append(
            Deduction(
                points=4,
                reason="Longer than two pages." if pages and pages > 2 else "Very long resume.",
                suggestion="Keep it to one or two pages; cut older or less relevant detail.",
            )
        )
    elif chars < SHORT_CHARS:
        deductions.append(
            Deduction(
                points=4,
                reason="Very little text.",
                suggestion="Add concrete detail: what you built, with which tools, and results.",
            )
        )
    return _part("formatting", "Formatting risks", FORMATTING_MAX, deductions)


# ── seniority ─────────────────────────────────────────────────────────────────────

LEVEL_POINTS = 12.0
YEARS_POINTS = 8.0


@dataclass
class Fit:
    resume_level: str
    resume_years: float
    job_level: str | None
    job_min_years: float | None


def score_seniority(fit: Fit) -> ScorePart:
    deductions, notes = [], []
    if fit.job_level in LEVEL and fit.resume_level in LEVEL:
        gap = LEVEL[fit.job_level] - LEVEL[fit.resume_level]
        if abs(gap) >= 2:
            lost, how = LEVEL_POINTS, "far"
        elif abs(gap) == 1:
            lost, how = LEVEL_POINTS / 2, "one level"
        else:
            lost, how = 0, ""
        if lost:
            direction = "above" if gap > 0 else "below"
            deductions.append(
                Deduction(
                    points=lost,
                    reason=f"The role is {fit.job_level}-level, {how} {direction} your "
                    f"{fit.resume_level} profile.",
                    suggestion="Apply anyway if the work fits, but expect screening on level."
                    if gap > 0
                    else "You may be overqualified; say why this role fits you.",
                )
            )
    else:
        notes.append(Note(message="The posting doesn't state a level, so none was checked."))
    if fit.job_min_years:
        short = fit.job_min_years - fit.resume_years
        if short > 0:
            deductions.append(
                Deduction(
                    points=round(YEARS_POINTS * min(1.0, short / fit.job_min_years), 1),
                    reason=f"Asks for {fit.job_min_years:g}+ years; your resume shows "
                    f"{fit.resume_years:g} years of professional experience.",
                    suggestion="Count relevant internships, freelance and open-source work, "
                    "with dates, if you haven't.",
                )
            )
    return _part("seniority", "Seniority and experience", SENIORITY_MAX, deductions, notes)
