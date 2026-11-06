"""One module per job source. Each exposes a `Source` with:

- `fetch(client)`: download the feed into FeedPages (network only, no parsing);
- `parse(page)`: turn one page into RawJobs (pure, so tests can feed fixtures);
- `complete_feed`: whether a page lists *every* open job in its scope. Only then can a
  job that disappears from the feed be marked inactive.
"""

from typing import Protocol

import httpx

from ingestion.models import FeedPage, RawJob


class Source(Protocol):
    name: str
    complete_feed: bool

    async def fetch(self, client: httpx.AsyncClient) -> list[FeedPage | Exception]: ...

    def parse(self, page: FeedPage) -> list[RawJob]: ...


def all_sources() -> dict[str, Source]:
    from ingestion.scrapers.greenhouse import GreenhouseSource
    from ingestion.scrapers.remoteok import RemoteOKSource
    from ingestion.scrapers.remotive import RemotiveSource

    sources: list[Source] = [RemotiveSource(), RemoteOKSource(), GreenhouseSource()]
    return {s.name: s for s in sources}
