"""Classify each normalized job against what's already stored.

- Same (source, source_id) as a stored job: "unchanged" or "changed" by content hash.
- Otherwise "duplicate" if an active job already has the same content hash (any
  source), or the same company + title on a *different* source (one posting
  cross-listed on two boards); else "new".

Within one source, company + title repeats are kept: Greenhouse lists one role per
location as separate postings.
"""

from dataclasses import dataclass
from typing import Literal

from ingestion.normalize import NormalizedJob, dedupe_key

Kind = Literal["new", "changed", "unchanged", "duplicate"]


@dataclass(frozen=True)
class StoredJob:
    id: int
    source: str
    source_id: str
    content_hash: str
    company: str
    title: str
    is_active: bool


class Deduper:
    def __init__(self, stored: list[StoredJob]) -> None:
        self.by_source_id = {(j.source, j.source_id): j for j in stored}
        active = [j for j in stored if j.is_active]
        self.hashes: dict[str, tuple[str, str]] = {
            j.content_hash: (j.source, j.source_id) for j in active
        }
        self.keys: dict[str, str] = {dedupe_key(j.company, j.title): j.source for j in active}

    def classify(self, job: NormalizedJob) -> tuple[Kind, int | None]:
        stored = self.by_source_id.get((job.source, job.source_id))
        if stored is not None:
            kind: Kind = "unchanged" if stored.content_hash == job.content_hash else "changed"
            return kind, stored.id

        owner = self.hashes.get(job.content_hash)
        if owner is not None and owner != (job.source, job.source_id):
            return "duplicate", None
        key_source = self.keys.get(job.dedupe_key)
        if key_source is not None and key_source != job.source:
            return "duplicate", None

        # Register it, so a copy later in the same run (another source) is caught too.
        self.hashes[job.content_hash] = (job.source, job.source_id)
        self.keys.setdefault(job.dedupe_key, job.source)
        return "new", None
