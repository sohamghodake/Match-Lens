"""Scrapers and normalization, on synthetic payloads shaped like the real feeds."""

import html
from datetime import UTC, datetime

import pytest

from ingestion.models import FeedPage, RawJob
from ingestion.normalize import (
    content_hash,
    dedupe_key,
    html_to_text,
    is_remote,
    is_tech_role,
    normalize,
)
from ingestion.scrapers.greenhouse import Board, GreenhouseSource
from ingestion.scrapers.remoteok import RemoteOKSource, format_salary
from ingestion.scrapers.remotive import RemotiveSource

REMOTIVE = {
    "0-legal-notice": "...",
    "job-count": 1,
    "jobs": [
        {
            "id": 101, "url": "https://remotive.com/remote-jobs/software-dev/backend-101",
            "title": "Senior Backend Engineer", "company_name": "Testco Labs",
            "category": "Software Development", "candidate_required_location": "Worldwide",
            "publication_date": "2026-11-04T16:53:35", "salary": " $120k - $150k ",
            "description": "<p>Python, Go and PostgreSQL.</p>", "tags": ["python"],
        }
    ],
}  # fmt: skip
REMOTEOK = [
    {"legal": "API Terms of Service: Please link back..."},
    {
        "id": "555", "epoch": 1793894407, "date": "2026-11-05T16:00:07+00:00",
        "position": "AI Engineer", "company": "Silver.dev", "location": "",
        "salary_min": 60000, "salary_max": 110000, "tags": ["golang"],
        "url": "https://remoteOK.com/remote-jobs/555", "description": "<p>LLMs and Python</p>",
    },
]  # fmt: skip
GREENHOUSE = {
    "jobs": [
        {
            "id": 9001, "title": " Staff Software Engineer, Platform ",
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/9001",
            "company_name": "Acme", "location": {"name": "Remote, United States"},
            "first_published": "2026-07-22T13:38:40-04:00",
            "updated_at": "2026-11-05T12:00:00-05:00",
            "content": html.escape("<h2>About</h2><ul><li>Kubernetes</li><li>Terraform</li></ul>"),
        }
    ]
}  # fmt: skip


def test_remotive_parse() -> None:
    [job] = RemotiveSource().parse(FeedPage("remotive", "*", REMOTIVE))
    assert (job.source_id, job.company, job.location) == ("101", "Testco Labs", "Worldwide")
    assert job.salary == "$120k - $150k" and job.remote is True
    assert job.posted_at == datetime(2026, 11, 4, 16, 53, 35, tzinfo=UTC)


def test_remoteok_parse_skips_legal_notice_and_formats_salary() -> None:
    [job] = RemoteOKSource().parse(FeedPage("remoteok", "*", REMOTEOK))
    assert (job.source_id, job.title, job.location) == ("555", "AI Engineer", None)
    assert job.salary == "$60k–$110k"
    assert job.posted_at == datetime.fromtimestamp(1793894407, tz=UTC)


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    [(0, 0, None), (90000, 90000, "$90k"), (0, 120000, "$120k"), (85500, 0, "$85.5k")],
)
def test_format_salary(low: int, high: int, expected: str | None) -> None:
    assert format_salary(low, high) == expected


def test_greenhouse_parse_and_unescape() -> None:
    source = GreenhouseSource([Board("acme")])
    [job] = source.parse(FeedPage("greenhouse", "acme", GREENHOUSE))
    assert job.source_id == "acme:9001"
    assert job.title == "Staff Software Engineer, Platform"
    assert job.posted_at is not None and job.posted_at.year == 2026 and job.posted_at.month == 7
    assert job.remote is None  # inferred from the location later
    assert html_to_text(job.description_html) == "About\n\n• Kubernetes\n• Terraform"


def test_remote_by_default_board() -> None:
    source = GreenhouseSource([Board("elastic", remote_by_default=True)])
    payload = {"jobs": [{**GREENHOUSE["jobs"][0], "location": {"name": "United States"}}]}
    [job] = source.parse(FeedPage("greenhouse", "elastic", payload))
    assert job.remote is True


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Senior Backend Engineer", True),
        ("Staff Data Scientist, Marketing", True),
        ("Software Engineer, Sales Tools", True),
        ("Product Designer", True),
        ("Senior Sales Engineer", False),
        ("Principal Technical Marketing Engineer", False),
        ("Enterprise Account Executive", False),
        ("Recruiter, Engineering", False),
        ("Office Manager", False),
    ],
)
def test_is_tech_role(title: str, expected: bool) -> None:
    assert is_tech_role(title) is expected


def raw(**overrides: object) -> RawJob:
    base = {
        "source": "greenhouse", "source_id": "acme:1", "url": "https://x/1",
        "title": "Software Engineer", "company": "Acme", "location": "San Francisco, CA",
        "description_html": "<p>Python</p>", "posted_at": None,
    }  # fmt: skip
    return RawJob(**{**base, **overrides})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("location", "title", "expected"),
    [
        ("Remote, United States", "Software Engineer", True),
        ("Distributed", "Software Engineer", True),
        ("Anywhere in EMEA", "Software Engineer", True),
        ("San Francisco, CA", "Software Engineer (Remote)", True),
        ("Hybrid", "Software Engineer", False),
        ("San Francisco, CA", "Software Engineer", False),
        (None, "Software Engineer", False),
    ],
)
def test_is_remote(location: str | None, title: str, expected: bool) -> None:
    assert is_remote(raw(location=location, title=title)) is expected


def test_normalize_skip_reasons_and_fields() -> None:
    assert normalize(raw(title="Account Executive", location="Remote")) == "not_tech"
    assert normalize(raw(location="Hybrid")) == "not_remote"
    assert normalize(raw(location="Remote", description_html="<p> </p>")) == "empty"

    job = normalize(
        raw(
            title="Senior  Python Developer",
            location="Remote",
            description_html="<p>Python, Go and k8s</p>",
        )
    )
    assert not isinstance(job, str)
    assert job.title == "Senior Python Developer"
    assert job.seniority == "senior"
    assert job.skills == ["Python", "Go", "Kubernetes"]


def test_dedupe_key_ignores_noise() -> None:
    assert dedupe_key("Askable Inc.", "Software Engineer (Remote)") == dedupe_key(
        "askable", "Software Engineer - remote"
    )
    assert dedupe_key("Acme", "Backend Engineer") != dedupe_key("Acme", "Frontend Engineer")


def test_content_hash_tracks_visible_changes_only() -> None:
    base = content_hash("Engineer", "Acme", "Remote", "Build things.")
    assert content_hash(" engineer", "ACME", "remote", "Build  things") == base
    assert content_hash("Engineer", "Acme", "Remote", "Build other things.") != base


async def test_llm_skills_only_keep_skills_the_text_mentions() -> None:
    from ingestion.llm_skills import JobSkills, enrich_skills

    class FakeLLM:
        async def structured(self, prompt: str, schema: type, **_: object) -> JobSkills:
            return JobSkills(required=["Python", "Protocol Buffers"], nice_to_have=["AWS", "C"])

    job = normalize(
        raw(
            location="Remote", description_html="<p>Python. We use C, Rust and Protocol Buffers</p>"
        )
    )
    assert not isinstance(job, str)
    job.skills = ["Python"]
    stats = await enrich_skills([job], FakeLLM(), max_jobs=5)  # type: ignore[arg-type]
    assert job.skills == ["Python", "Protocol Buffers", "C"]  # AWS isn't in the text
    assert (stats.added, stats.rejected, stats.attempted) == (2, 1, 1)
