"""Remotive public API: https://github.com/remotive-com/remote-jobs-api

Terms: link back to the Remotive URL and name Remotive as the source; don't resubmit
jobs to other job sites (Google Jobs, LinkedIn...); at most ~4 requests a day (more
than 2 a minute are blocked). So: one request per run for all jobs, filtered locally.
The free API lists far fewer jobs than the site (12 on 6 Nov 2026); jobs are 24 h delayed.
"""

from datetime import UTC, datetime

import httpx

from ingestion.models import FeedPage, RawJob

API_URL = "https://remotive.com/api/remote-jobs"


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class RemotiveSource:
    name = "remotive"
    complete_feed = True  # the API returns every active listing

    async def fetch(self, client: httpx.AsyncClient) -> list[FeedPage | Exception]:
        try:
            response = await client.get(API_URL)
            response.raise_for_status()
            return [FeedPage(self.name, "*", response.json())]
        except (httpx.HTTPError, ValueError) as exc:
            return [exc]

    def parse(self, page: FeedPage) -> list[RawJob]:
        jobs = []
        for item in page.payload.get("jobs", []):
            jobs.append(
                RawJob(
                    source=self.name,
                    source_id=str(item["id"]),
                    url=item["url"],
                    title=item["title"],
                    company=item["company_name"],
                    location=(item.get("candidate_required_location") or "").strip() or None,
                    description_html=item.get("description") or "",
                    posted_at=_parse_date(item.get("publication_date")),
                    salary=(item.get("salary") or "").strip() or None,
                    tags=list(item.get("tags") or []),
                    remote=True,
                )
            )
        return jobs
