from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class FeedPage:
    """One fetched payload. `scope` says which jobs the page covers ("*" for the whole
    source, a board token for Greenhouse), so a job missing from a complete page can be
    marked inactive without touching scopes that failed to fetch."""

    source: str
    scope: str
    payload: Any


@dataclass
class RawJob:
    """A posting as the source gives it; every scraper returns this shape."""

    source: str
    source_id: str  # unique within the source; Greenhouse uses "board:job_id"
    url: str  # the listing on the source site (sources require linking back to it)
    title: str
    company: str
    location: str | None
    description_html: str
    posted_at: datetime | None
    salary: str | None = None
    tags: list[str] = field(default_factory=list)
    # True when the source only lists remote jobs; None means infer from location.
    remote: bool | None = None
