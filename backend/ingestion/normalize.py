"""RawJob -> NormalizedJob: plain-text description, remote flag, seniority, skills,
and the keys used for change detection and de-duplication."""

import hashlib
import html
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from bs4 import BeautifulSoup

from app.parsing.locations import parse_places
from app.parsing.seniority import seniority_from_title
from app.parsing.skills import find_known_skills
from ingestion.models import RawJob

SkipReason = Literal["not_tech", "not_remote", "empty"]

# Job families MatchLens matches resumes against. Titles are checked, not descriptions:
# a sales role at a software company mentions "engineering" constantly.
TECH_TITLE = re.compile(
    r"\b(engineer(ing)?|developer|programmer|software|swe|sde|data|analytics|scientist|"
    r"machine learning|ml|ai|llm|devops|sre|site reliability|infrastructure|platform|"
    r"security|architect|qa|quality assurance|test(ing)?|frontend|front[- ]end|backend|"
    r"back[- ]end|full[- ]?stack|mobile|ios|android|cloud|database|dba|designer|ux|ui|"
    r"product manager|technical program manager|researcher|research scientist|"
    r"technical writer|it support|systems administrator|sysadmin|network)\b",
    re.I,
)
NOT_TECH_TITLE = re.compile(
    # Gig work that mentions AI but isn't an engineering job.
    r"\b(annotat(or|ion)|data label(l)?ing|rater|content reviewer|ai trainer|ai tutor)\b|"
    r"\b(sales|account (executive|manager)|business development|recruit(er|ing)|talent|"
    r"marketing|counsel|attorney|legal|paralegal|accountant|accounting|payroll|tax|"
    r"finance|financial|customer success|people partner|hr|human resources|copywriter|"
    r"content writer|executive assistant|office manager)\b",
    re.I,
)
# Unmistakably technical: these win over a department word ("Data Scientist, Marketing").
CORE_TECH_TITLE = re.compile(
    r"\b(software (engineer|developer)|data (scientist|engineer)|machine learning|"
    r"ml engineer|developer|research (engineer|scientist)|(site reliability|devops|"
    r"backend|frontend|full[- ]?stack|platform|infrastructure|security) engineer)\b",
    re.I,
)
REMOTE_WORDS = re.compile(
    r"\b(remote|distributed|anywhere|worldwide|global|work from home|wfh|home[- ]based|virtual)\b",
    re.I,
)


@dataclass
class NormalizedJob:
    source: str
    source_id: str
    url: str
    title: str
    company: str
    location: str | None
    remote: bool
    salary: str | None
    seniority: str | None
    description: str
    skills: list[str]
    regions: list[str]
    posted_at: datetime | None
    content_hash: str
    dedupe_key: str  # company + title, for spotting one job posted on two sources


# UTF-8 text that was decoded as Latin-1 / Windows-1252 somewhere upstream ("â\x80\x99"
# instead of "’"); Remote OK's feed has some.
_MOJIBAKE = re.compile(
    "[\u00c2-\u00f4][\u0080-\u00bf\u0152\u0153\u0160\u0161\u0178\u017d"
    "\u017e\u0192\u02c6\u02dc\u2013\u2014\u2018-\u201e\u2020-\u2022"
    "\u2026\u2030\u2039\u203a\u20ac\u2122]{1,3}"
)


def fix_mojibake(text: str) -> str:
    def repair(match: re.Match[str]) -> str:
        chunk = match.group(0)
        for encoding in ("latin-1", "cp1252"):
            try:
                return chunk.encode(encoding).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
        return chunk

    return _MOJIBAKE.sub(repair, text) if text else text


def html_to_text(raw: str) -> str:
    if "&lt;" in raw and "<" not in raw:  # entity-escaped HTML (Greenhouse)
        raw = html.unescape(raw)
    soup = BeautifulSoup(raw, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for item in soup.find_all("li"):
        item.insert_before("\n• ")
    for tag in soup.find_all(["br", "p", "div", "h1", "h2", "h3", "h4", "tr", "ul", "ol"]):
        tag.insert_after("\n")
    text = soup.get_text()
    text = text.replace(" ", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_tech_role(title: str) -> bool:
    if CORE_TECH_TITLE.search(title):
        return True
    return bool(TECH_TITLE.search(title)) and not NOT_TECH_TITLE.search(title)


def is_remote(raw: RawJob) -> bool:
    if raw.remote is not None:
        return raw.remote
    return bool(REMOTE_WORDS.search(raw.location or "") or REMOTE_WORDS.search(raw.title))


def _norm(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", text or "").lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


_COMPANY_SUFFIX = re.compile(r"\b(inc|llc|ltd|limited|gmbh|corp|corporation|co|plc|sa|bv)$")
_TITLE_NOISE = re.compile(r"\b(remote|hybrid|us|usa|uk|eu|emea|apac|latam|worldwide)\b")


def dedupe_key(company: str, title: str) -> str:
    company_key = _COMPANY_SUFFIX.sub("", _norm(company)).strip()
    title_key = re.sub(r"\s+", " ", _TITLE_NOISE.sub("", _norm(title))).strip()
    return f"{company_key}|{title_key}"


def job_places(location: str | None, title: str) -> list[str]:
    """Places from the location field; failing that, from the title's tagged segments
    ("Staff AI Engineer | USA | Remote"), but never the main title text, where
    "Asia Pacific Payments" names a team, not a location."""
    places = parse_places(location)
    if places:
        return places
    segments = re.split(r"[|()\[\]–—]| - ", title)[1:]
    return parse_places(" ; ".join(s for s in segments if len(s.split()) <= 4))


def content_hash(title: str, company: str, location: str | None, description: str) -> str:
    """Changes whenever anything a user would see changes, so the job is re-embedded."""
    joined = "\x1f".join(_norm(part) for part in (title, company, location, description))
    return hashlib.sha256(joined.encode()).hexdigest()


def normalize(raw: RawJob) -> NormalizedJob | SkipReason:
    raw.title, raw.company = fix_mojibake(raw.title), fix_mojibake(raw.company)
    raw.location = fix_mojibake(raw.location) if raw.location else raw.location
    raw.description_html = fix_mojibake(raw.description_html)
    title = " ".join(raw.title.split())
    if not is_tech_role(title):
        return "not_tech"
    if not is_remote(raw):
        return "not_remote"
    description = html_to_text(raw.description_html)
    if not description:
        return "empty"
    company = " ".join(raw.company.split())
    return NormalizedJob(
        source=raw.source,
        source_id=raw.source_id,
        url=raw.url,
        title=title,
        company=company,
        location=raw.location,
        remote=True,
        salary=raw.salary,
        seniority=seniority_from_title(title),
        description=description,
        skills=find_known_skills(f"{title}\n{description}"),
        regions=job_places(raw.location, title),
        posted_at=raw.posted_at,
        content_hash=content_hash(title, company, raw.location, description),
        dedupe_key=dedupe_key(company, title),
    )


def embedding_text(job: NormalizedJob, max_description: int = 1500) -> str:
    """Title, level and skills first: bge-small reads only the first 512 tokens."""
    parts = [job.title]
    if job.seniority:
        parts.append(f"{job.seniority} level")
    if job.skills:
        parts.append("Skills: " + ", ".join(job.skills))
    parts.append(job.description[:max_description])
    return ". ".join(parts)
