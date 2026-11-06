"""Rule-based seniority: used when the LLM fails, and for job titles during ingestion."""

import re

from app.parsing.schema import Seniority

# Checked in this order: "Senior Engineering Manager" is lead, "Senior Intern" is intern.
_TITLE_RULES: list[tuple[Seniority, re.Pattern[str]]] = [
    ("intern", re.compile(r"\b(intern(ship)?|trainee|apprentice|co-?op)\b", re.I)),
    (
        "lead",
        re.compile(
            r"\b(lead|staff|principal|distinguished|head of|director|vp|vice president|"
            r"chief|cto|architect|(engineering|development|technical|tech) manager|"
            r"manager,? engineering)\b",
            re.I,
        ),
    ),
    ("senior", re.compile(r"\b(senior|sr\.?)(?=\s|$)|\b(iii|iv|level 3|l5)\b", re.I)),
    ("junior", re.compile(r"\b(junior|jr\.?|entry[- ]level|graduate|new grad)(?=\s|$)", re.I)),
]


def seniority_from_title(title: str) -> Seniority | None:
    for level, pattern in _TITLE_RULES:
        if pattern.search(title):
            return level
    return None


def seniority_from_years(years: float) -> Seniority:
    if years < 2:
        return "junior"
    if years < 5:
        return "mid"
    return "senior"  # "lead" only ever comes from a title


def infer_seniority(latest_title: str | None, years: float, *, only_internships: bool) -> Seniority:
    """Most recent title first (it's the strongest signal), then years of experience."""
    if latest_title and (level := seniority_from_title(latest_title)):
        return level
    if only_internships:
        return "intern"
    return seniority_from_years(years)


def is_internship(title: str) -> bool:
    return seniority_from_title(title) == "intern"
