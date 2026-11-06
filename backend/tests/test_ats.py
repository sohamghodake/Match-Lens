import random

import pytest
from pydantic import BaseModel

from app.ats import score
from app.ats.analyze import JDAnalysis, analyze, analyze_with_rules, min_years_from_text
from app.llm.client import LLMError

RESUME = """Jane Doe
Experience
Backend Intern, Acme (Jun 2025 - Aug 2025): built REST APIs with FastAPI and PostgreSQL.
Projects
Ledger: a payments service in Go. Also practiced DSA.
Education
B.Tech Computer Science, 2027
Technical Skills
Python, Go, PostgreSQL, Docker
"""


@pytest.fixture(autouse=True)
def _empty_analysis_cache() -> None:
    from app.ats import analyze as module

    module._CACHE.clear()


FILE_OK = {"has_email": True, "has_phone": True, "columns": 1, "tables": 0, "pages": 1,
           "chars": 3000}  # fmt: skip


def consistent(part: score.ScorePart) -> bool:
    lost = round(sum(d.points for d in part.deductions), 1)
    return round(part.max_points - lost, 1) == part.points and all(
        d.points > 0 and d.reason and d.suggestion for d in part.deductions
    )


# ── keywords ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("keyword", "status", "written"),
    [
        ("FastAPI", "found", None),
        ("Postgres", "synonym", "PostgreSQL"),  # alias of the same skill, quoted as written
        ("data structures", "synonym", "DSA"),
        ("Kubernetes", "missing", None),
    ],
)
def test_match_keyword(keyword: str, status: str, written: str | None) -> None:
    result = score.match_keyword(keyword, RESUME, ["Python"])
    assert (result.status, result.resume_term) == (status, written)


def test_everyday_words_are_not_synonyms() -> None:
    # "REST APIs" has the alias "rest", but "the rest of the team" isn't REST.
    result = score.match_keyword("REST APIs", "I helped the rest of the team.", [])
    assert result.status == "missing"


def test_keyword_weights_and_notes() -> None:
    part, results = score.score_keywords(
        ["Python", "Kubernetes"], ["Terraform", "Postgres"], RESUME, []
    )
    # Weights: required 2, preferred 1, out of 6: Kubernetes 40*2/6, Terraform 40*1/6.
    assert [d.points for d in part.deductions] == [13.3, 6.7]
    assert part.points == 20.0 and consistent(part)
    assert [r.importance for r in results] == ["required", "required", "preferred", "preferred"]
    assert "Postgres" in part.notes[0].message


def test_all_keywords_missing_loses_exactly_the_maximum() -> None:
    part, _ = score.score_keywords(["Rust", "Scala", "Elixir"], [], "nothing relevant", [])
    assert part.points == 0 and consistent(part)


# ── sections, formatting, seniority ───────────────────────────────────────────────


def test_sections_found_and_missing() -> None:
    assert score.find_sections(RESUME) == {"experience", "projects", "education", "skills"}
    part = score.score_sections(RESUME, FILE_OK, has_location=False)
    assert part.points == 20 and consistent(part)
    assert "city or country" in part.notes[0].message

    student = "Projects\nThing\nSkills\nPython"
    part = score.score_sections(student, {"has_email": True}, has_location=True)
    reasons = [d.reason for d in part.deductions]
    assert any("projects carry the weight" in r for r in reasons)  # 3, not 6
    assert any("phone" in r for r in reasons) and any("Education" in r for r in reasons)
    assert part.points == 20 - 2 - 3 - 4 and consistent(part)


def test_formatting_risks() -> None:
    risky = {"columns": 2, "tables": 1, "pages": 3, "chars": 12_000}
    part = score.score_formatting(risky)
    assert [d.points for d in part.deductions] == [8, 5, 4] and consistent(part)
    assert score.score_formatting({**FILE_OK, "chars": 500}).points == 16


@pytest.mark.parametrize(
    ("resume_level", "years", "job_level", "min_years", "points"),
    [
        ("junior", 1, "junior", None, 20),
        ("intern", 0, "junior", 1, 20 - 6 - 8),
        ("junior", 1, "senior", 5, 20 - 12 - 6.4),
        ("senior", 8, "junior", None, 20 - 12),
        ("mid", 3, None, None, 20),
    ],
)
def test_seniority(
    resume_level: str, years: float, job_level: str | None, min_years: float | None, points: float
) -> None:
    part = score.score_seniority(score.Fit(resume_level, years, job_level, min_years))
    assert part.points == round(points, 1) and consistent(part)


def test_every_deduction_is_explained_for_random_inputs() -> None:
    """The exit check: across many inputs, deductions always add up to the points lost."""
    rng = random.Random(7)
    skills = ["Python", "Go", "Rust", "Kubernetes", "Postgres", "React", "AWS", "Kafka"]
    for _ in range(300):
        required = rng.sample(skills, rng.randint(0, 6))
        preferred = rng.sample(skills, rng.randint(0, 4))
        facts = {
            "has_email": rng.random() > 0.3, "has_phone": rng.random() > 0.3,
            "columns": rng.choice([1, 2]), "tables": rng.choice([0, 0, 2]),
            "pages": rng.choice([None, 1, 3]), "chars": rng.choice([400, 3000, 12000]),
        }  # fmt: skip
        parts = [
            score.score_keywords(required, preferred, RESUME, ["Python"])[0],
            score.score_sections(rng.choice([RESUME, "Projects\nx"]), facts, rng.random() > 0.5),
            score.score_formatting(facts),
            score.score_seniority(
                score.Fit(
                    rng.choice(["intern", "junior", "mid", "senior", "lead"]),
                    rng.choice([0, 1, 4, 10]),
                    rng.choice([None, "intern", "junior", "senior", "lead"]),
                    rng.choice([None, 1, 3, 7]),
                )
            ),
        ]
        assert all(consistent(p) for p in parts)
        assert 0 <= sum(p.points for p in parts) <= 100


# ── job description analysis ──────────────────────────────────────────────────────

JD = """Backend Engineer
Requirements: 3+ years of professional experience with Python, Postgres and Docker.
Nice to have: JavaScript/TypeScript, Kubernetes. We love hackathons and AI tools."""


class FakeLLM:
    def __init__(self, reply: JDAnalysis | Exception) -> None:
        self.reply = reply

    async def structured[T: BaseModel](self, prompt: str, schema: type[T], **_: object) -> T:
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply  # type: ignore[return-value]


def test_min_years_from_text() -> None:
    assert min_years_from_text(JD) == 3
    assert min_years_from_text("We were founded 10 years ago.") is None
    assert min_years_from_text("2-4 years of industry experience") == 2


async def test_llm_keywords_are_grounded_split_and_filtered() -> None:
    reply = JDAnalysis(
        title="Backend Engineer",
        seniority="mid",
        min_years=3,
        required=["Python", "Postgres", "Docker", "Rust"],  # Rust isn't in the posting
        preferred=["JavaScript/TypeScript", "hackathons", "AI tools"],
    )
    jd = await analyze(JD, FakeLLM(reply))  # type: ignore[arg-type]
    assert jd.method == "llm"
    assert jd.required == ["Python", "Postgres", "Docker"]
    # Split, generic phrases dropped, and the dictionary adds Kubernetes.
    assert jd.preferred == ["JavaScript", "TypeScript", "Kubernetes"]


async def test_llm_failure_uses_rules() -> None:
    jd = await analyze(JD, FakeLLM(LLMError("HTTP 429")))  # type: ignore[arg-type]
    assert jd.method == "rules"
    assert jd.title == "Backend Engineer" and jd.min_years == 3
    assert {"Python", "PostgreSQL", "Docker", "Kubernetes"} <= set(jd.required)


def test_rules_title_needs_a_short_first_line() -> None:
    assert (
        analyze_with_rules("We are a company that builds many things for many people " * 3).title
        is None
    )


async def test_same_posting_is_analyzed_once() -> None:
    from app.ats import analyze as module

    module._CACHE.clear()

    class CountingLLM(FakeLLM):
        calls = 0

        async def structured[T: BaseModel](self, prompt: str, schema: type[T], **_: object) -> T:
            CountingLLM.calls += 1
            return JDAnalysis(title="X", required=["Python"])  # type: ignore[return-value]

    llm = CountingLLM(JDAnalysis())
    first = await analyze(JD, llm)  # type: ignore[arg-type]
    second = await analyze("  " + JD.replace("\n", "\n  "), llm)  # same text, other spacing
    assert CountingLLM.calls == 1 and first is second
    # A failed analysis isn't cached, so the next request tries the model again.
    module._CACHE.clear()
    await analyze(JD, FakeLLM(LLMError("HTTP 429")))  # type: ignore[arg-type]
    assert module._CACHE == {}
