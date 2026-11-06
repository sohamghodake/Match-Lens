import pytest

from app.matching import rerank
from app.matching.score import rule_reason, score_candidates, seniority_penalty, skill_overlap
from app.matching.service import clean_missing
from app.parsing.schema import Project, ResumeProfile, Role


def test_skill_overlap_keeps_job_order_and_ignores_case() -> None:
    matched, missing = skill_overlap(["Python", "Go", "Kafka"], ["kafka", "python"])
    assert matched == ["Python", "Kafka"]
    assert missing == ["Go"]


@pytest.mark.parametrize(
    ("resume", "job", "penalty"),
    [
        ("intern", "senior", 0.25),
        ("junior", "mid", 0.08),
        ("senior", "senior", 0.0),
        ("lead", "junior", 0.10),
        ("intern", None, 0.0),  # no level in the title: no penalty
    ],
)
def test_seniority_penalty(resume: str, job: str | None, penalty: float) -> None:
    assert seniority_penalty(resume, job) == penalty


def test_score_candidates_blends_similarity_and_skills() -> None:
    scored = score_candidates(
        [
            (1, 0.80, ["Python", "FastAPI"], None),  # most similar, full skill coverage
            (2, 0.70, ["Java", "Spring"], None),  # no skills in common
            (3, 0.79, ["Python", "FastAPI"], "senior"),  # good match, far above level
        ],
        resume_skills=["Python", "FastAPI"],
        resume_level="junior",
    )
    assert [s.job_id for s in scored] == [1, 3, 2]
    assert scored[0].similarity_norm == 1.0 and scored[-1].similarity_norm == 0.0
    assert scored[1].penalty == 0.25
    assert all(0.0 <= s.hybrid <= 1.0 for s in scored)


def test_rule_reason_names_skills() -> None:
    [s] = score_candidates([(1, 0.8, ["Python", "Go", "SQL"], None)], ["Python", "SQL"], "mid")
    assert rule_reason(s, 3) == "You have 2 of its 3 listed skills: Python, SQL."


def profile() -> ResumeProfile:
    return ResumeProfile(
        headline="AI/ML Engineer Intern",
        seniority="intern",
        total_years_experience=0,
        skills=["Python", "Go", "PostgreSQL"],
        roles=[
            Role(title="AI/ML Engineer Intern", company="Hum1ai", start="2025-10", end="2026-01")
        ],
        education=[],
        projects=[Project(name="Hive", summary="Multi-agent orchestration", skills=["Python"])],
    )


def card(n: int, description: str = "x") -> rerank.JobCard:
    return rerank.JobCard(n, f"Engineer {n}", "Acme", None, ["Python"] * 20, description)


def test_snippet_skips_company_boilerplate() -> None:
    text = "At Acme we believe in many things. " * 5 + "Requirements: Python and SQL."
    assert rerank.snippet(text).startswith("Requirements: Python and SQL.")


def test_prompt_for_20_long_jobs_stays_compact() -> None:
    long_description = "Requirements: " + "lots of detail " * 2000
    prompt = rerank.build_prompt(profile(), [card(n, long_description) for n in range(1, 21)])
    assert "Projects: Hive: Multi-agent orchestration [Python]" in prompt
    assert "[20] Engineer 20" in prompt
    # ~4 characters per token: well under Groq's free 8,000 tokens per minute.
    assert len(prompt) < 12_000


def test_merge_ignores_bad_numbers_and_repeats() -> None:
    result = rerank.RerankResult(
        jobs=[
            rerank.RankedJob(job=2, score=90, reason="  Great   fit. ", missing_skills=["k8s"]),
            rerank.RankedJob(job=2, score=10, reason="repeat", missing_skills=[]),
            rerank.RankedJob(job=7, score=50, reason="out of range", missing_skills=[]),
            rerank.RankedJob(job=1, score=40, reason="word " * 100, missing_skills=[]),
        ]
    )
    judged = rerank.merge(result, count=3)
    assert set(judged) == {1, 2}
    assert judged[2].score == 90 and judged[2].reason == "Great fit."
    assert judged[2].missing_skills == ["Kubernetes"]
    assert len(judged[1].reason) <= rerank.MAX_REASON_CHARS + 1


def test_clean_missing_keeps_real_skills_the_candidate_lacks() -> None:
    suggested = ["Docker", "Leadership", "Rust", "3D perception", "Kafka"]
    assert clean_missing(suggested, job_skills=["Rust"], resume_skills=["Docker"]) == [
        "Rust",  # listed by the job
        "Kafka",  # a known skill
    ]
