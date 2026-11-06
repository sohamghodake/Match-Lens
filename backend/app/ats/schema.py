import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.parsing.schema import Seniority


class AtsRequest(BaseModel):
    resume_id: uuid.UUID
    # Exactly one: a pasted description, or a stored job's id (from the matches page).
    job_description: str | None = Field(None, min_length=50, max_length=20_000)
    job_id: int | None = None

    @model_validator(mode="after")
    def _one_source(self) -> "AtsRequest":
        if (self.job_description is None) == (self.job_id is None):
            raise ValueError("send either job_description or job_id")
        return self


class Deduction(BaseModel):
    points: float  # points lost, > 0
    reason: str
    suggestion: str


class Note(BaseModel):
    """Advice that costs no points."""

    message: str


class ScorePart(BaseModel):
    key: Literal["keywords", "sections", "formatting", "seniority"]
    name: str
    max_points: float
    points: float  # max_points minus the deductions
    deductions: list[Deduction]
    notes: list[Note] = []


class KeywordResult(BaseModel):
    keyword: str  # as the posting writes it
    importance: Literal["required", "preferred"]
    status: Literal["found", "synonym", "missing"]
    resume_term: str | None = None  # what the resume says, when it's a synonym


class JobSummary(BaseModel):
    title: str | None
    seniority: Seniority | None
    min_years: float | None


class AtsReport(BaseModel):
    resume_id: uuid.UUID
    generated_at: datetime
    score: float  # 0-100, the sum of the parts
    parts: list[ScorePart]
    keywords: list[KeywordResult]
    job: JobSummary
    analysis_method: Literal["llm", "rules"]
