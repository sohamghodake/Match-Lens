from typing import Literal

from pydantic import BaseModel, Field, field_validator

# One scale for resumes and jobs, so Phase 4 can compare them directly.
# "lead" covers staff, principal, architect and management titles.
Seniority = Literal["intern", "junior", "mid", "senior", "lead"]
SENIORITY_LEVELS: tuple[Seniority, ...] = ("intern", "junior", "mid", "senior", "lead")


class Role(BaseModel):
    title: str
    company: str
    location: str | None = None
    # "YYYY-MM" or "YYYY"; end may also be "present". None when the resume gives no date.
    start: str | None = None
    end: str | None = None


class Education(BaseModel):
    institution: str
    degree: str | None = None
    field: str | None = None
    end: str | None = None  # graduation year ("YYYY") when given


class Project(BaseModel):
    name: str
    summary: str | None = None
    skills: list[str] = []


class ResumeProfile(BaseModel):
    headline: str | None = None  # current or target title
    location: str | None = None  # as written, e.g. "Pune, India"
    country: str | None = None  # ISO code derived from location, e.g. "IN"
    seniority: Seniority
    total_years_experience: float = Field(ge=0)
    skills: list[str]
    roles: list[Role]  # most recent first
    education: list[Education]
    # Personal, academic or open-source work: for students, often the strongest signal.
    projects: list[Project] = []


# ── What the LLM is asked to fill in. Deliberately loose (free-text dates, optional
# fields) so that a messy but usable answer validates; code normalizes it afterwards.


class LLMRole(BaseModel):
    title: str
    company: str = Field(description="company name only, without its location")
    # Separate field so the model doesn't fold "Acme, Berlin" into the company name.
    location: str | None = None
    start: str | None = Field(None, description="as written, e.g. 'Mar 2021' or '2019'")
    end: str | None = Field(None, description="as written, or 'Present' if current")


class LLMEducation(BaseModel):
    institution: str
    degree: str | None = None
    field: str | None = None
    end: str | None = Field(None, description="graduation year or date, as written")


SENIORITY_SYNONYMS: dict[str, Seniority] = {
    "internship": "intern", "student": "intern", "trainee": "intern",
    "entry": "junior", "entry-level": "junior", "entry level": "junior", "jr": "junior",
    "graduate": "junior", "mid-level": "mid", "mid level": "mid", "middle": "mid",
    "intermediate": "mid", "senior-level": "senior", "sr": "senior", "staff": "lead",
    "principal": "lead", "manager": "lead", "director": "lead", "executive": "lead",
}  # fmt: skip


class LLMProject(BaseModel):
    name: str
    summary: str | None = Field(None, description="one line, at most 20 words")
    skills: list[str] = Field(default_factory=list, description="technologies used")


class LLMResume(BaseModel):
    headline: str | None = Field(None, description="the candidate's current or target title")
    location: str | None = Field(None, description="where the candidate lives, as written")
    seniority: Seniority
    total_years_experience: float | None = Field(None, ge=0, le=60)
    skills: list[str] = Field(description="technical skills, tools, languages, frameworks")
    roles: list[LLMRole] = Field(description="every job and internship, most recent first")
    education: list[LLMEducation] = []
    projects: list[LLMProject] = []

    @field_validator("seniority", mode="before")
    @classmethod
    def _seniority_any_case(cls, value: object) -> object:
        # Small models answer "Senior" or "Mid-level"; that's not worth a failed parse.
        if isinstance(value, str):
            key = value.strip().lower().rstrip(".")
            return SENIORITY_SYNONYMS.get(key, key)
        return value
