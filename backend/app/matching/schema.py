import json
import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.parsing.schema import Seniority


class MatchFilters(BaseModel):
    posted_within_days: int | None = Field(None, ge=1, le=365)
    # Only these levels; jobs whose title states no level are always included.
    seniority: list[Seniority] | None = None
    # Only jobs open to someone in this country (ISO code); None means anywhere.
    country: str | None = None
    # With a country set, also keep jobs whose posting doesn't say where.
    include_unspecified: bool = True

    def cache_key(self) -> str:
        data = self.model_dump()
        if data["seniority"]:
            data["seniority"] = sorted(data["seniority"])
        return json.dumps(data, sort_keys=True)


class JobOut(BaseModel):
    id: int
    title: str
    company: str
    location: str | None
    url: str  # the listing on its source site; sources require linking back to it
    source: str
    salary: str | None
    seniority: str | None
    posted_at: datetime | None
    regions: list[str] = []


class MatchOut(BaseModel):
    job: JobOut
    score: int  # 0-100: the LLM's score, or the stage-2 score scaled when not re-ranked
    reason: str
    matched_skills: list[str]
    missing_skills: list[str]
    similarity: float
    hybrid: float
    llm_score: int | None


class Timings(BaseModel):
    retrieve_ms: int
    score_ms: int
    rerank_ms: int
    total_ms: int


class MatchesOut(BaseModel):
    resume_id: uuid.UUID
    generated_at: datetime
    cached: bool
    reranked: bool
    model: str | None
    note: str | None  # shown to the user when the AI ranking was unavailable
    candidates: int
    filters: MatchFilters
    timings: Timings
    tokens: int | None  # prompt + completion tokens of the re-rank call
    matches: list[MatchOut]
