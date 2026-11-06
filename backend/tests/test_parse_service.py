from datetime import date

from pydantic import BaseModel

from app.llm.client import LLMError
from app.parsing.schema import LLMEducation, LLMResume, LLMRole
from app.parsing.service import embedding_text, parse_resume, parse_with_rules

TODAY = date(2026, 11, 6)


class FakeLLM:
    def __init__(self, reply: LLMResume | Exception) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    async def structured[T: BaseModel](self, prompt: str, schema: type[T], **_: object) -> T:
        self.prompts.append(prompt)
        if isinstance(self.reply, Exception):
            raise self.reply
        assert schema is LLMResume
        return self.reply  # type: ignore[return-value]


def llm_reply(**overrides: object) -> LLMResume:
    data: dict[str, object] = {
        "headline": "Senior Backend Engineer",
        "seniority": "senior",
        "total_years_experience": 25,  # deliberately wrong: code computes years itself
        "skills": ["JS", "Postgres", "python", "Python 3.12"],
        "roles": [
            LLMRole(
                title="Backend Engineer", company="Parcelpoint", start="Jul 2019", end="Feb 2022"
            ),
            LLMRole(
                title="Senior Backend Engineer",
                company="Ledgerly",
                location="Seattle, WA",
                start="Mar 2022",
                end="Present",
            ),
            LLMRole(
                title="Software Engineer Intern",
                company="Parcelpoint",
                start="May 2018",
                end="Aug 2018",
            ),
        ],
        "education": [
            LLMEducation(institution="University of Washington", degree="B.S.", end="June 2019")
        ],
    }
    data.update(overrides)
    return LLMResume.model_validate(data)


async def test_llm_output_is_normalized_and_years_are_computed() -> None:
    llm = FakeLLM(llm_reply())
    result = await parse_resume("resume text", llm, today=TODAY)  # type: ignore[arg-type]

    assert result.method == "llm" and result.warnings == []
    profile = result.profile
    assert [r.title for r in profile.roles] == [
        "Senior Backend Engineer",  # re-sorted most recent first
        "Backend Engineer",
        "Software Engineer Intern",
    ]
    assert (profile.roles[0].start, profile.roles[0].end) == ("2022-03", "present")
    assert profile.roles[0].location == "Seattle, WA"
    # Jul 2019 .. Nov 2026, internship excluded; not the LLM's 25.
    assert profile.total_years_experience == 7.4
    assert profile.skills == ["JavaScript", "PostgreSQL", "Python"]
    assert profile.education[0].end == "2019"
    assert profile.seniority == "senior"
    assert "resume text" in llm.prompts[0]


async def test_missing_and_unreadable_dates_produce_warnings() -> None:
    reply = llm_reply(roles=[LLMRole(title="Engineer", company="Acme", start="sometime", end=None)])
    result = await parse_resume("x", FakeLLM(reply), today=TODAY)  # type: ignore[arg-type]
    assert result.warnings == [
        'No start date found for Engineer at Acme ("sometime").',
        "No end date found for Engineer at Acme.",
    ]
    # No usable dates: fall back to the LLM's own estimate.
    assert result.profile.total_years_experience == 25


async def test_no_roles_warns_and_uses_llm_years() -> None:
    reply = llm_reply(roles=[], total_years_experience=None, headline=None)
    result = await parse_resume("x", FakeLLM(reply), today=TODAY)  # type: ignore[arg-type]
    assert result.warnings == ["No work experience was found."]
    assert result.profile.total_years_experience == 0
    assert result.profile.headline is None


async def test_llm_failure_falls_back_to_rules() -> None:
    text = """Jane Doe
Experience
Senior Data Engineer, Acme Corp
Mar 2020 – Present
Built Airflow and Spark pipelines on AWS with Postgres.
Data Engineering Intern, Beta Inc
Jun 2019 – Aug 2019
Education
B.S. Computer Science, State University, 2015 – 2019
Skills
Python, SQL, Docker, Go
"""
    result = await parse_resume(text, FakeLLM(LLMError("down")), today=TODAY)  # type: ignore[arg-type]
    assert result.method == "fallback"
    profile = result.profile
    assert profile.roles == []
    assert profile.seniority == "senior"  # from the most recent title
    # Mar 2020..Nov 2026 inclusive is 81 months; internship and degree dates excluded.
    assert profile.total_years_experience == 6.8
    assert set(profile.skills) == {
        "Apache Airflow",
        "Apache Spark",
        "AWS",
        "PostgreSQL",
        "Python",
        "SQL",
        "Docker",
    }
    assert len(result.warnings) == 1


def test_rules_without_experience_heading_skip_education_lines() -> None:
    text = "Engineer at Acme 2021 - 2023\nB.S. Physics, Some University 2015 - 2019"
    assert parse_with_rules(text, today=TODAY).profile.total_years_experience == 2.1


def test_embedding_text_is_compact() -> None:
    from app.parsing.service import build_profile

    profile, _ = build_profile(llm_reply(), today=TODAY)
    text = embedding_text(profile)
    assert text.startswith("Senior Backend Engineer. senior level, 7.4 years. Skills: JavaScript")
    assert "Senior Backend Engineer at Ledgerly" in text
