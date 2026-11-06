"""Remote OK public API: https://remoteok.com/api

Terms (the first array element): link back to the Remote OK URL with a followed link
(no rel="nofollow") and mention Remote OK as the source; don't use their logo. The feed
holds only the most recent ~100 jobs, so a job dropping out of it doesn't mean it closed.
"""

from datetime import UTC, datetime

import httpx

from ingestion.models import FeedPage, RawJob

API_URL = "https://remoteok.com/api"


def format_salary(low: int | None, high: int | None) -> str | None:
    """60000, 110000 -> "$60k–$110k" (Remote OK salaries are yearly USD; 0 means unset)."""

    def k(value: int) -> str:
        return f"${value / 1000:g}k"

    low, high = low or 0, high or 0
    if low and high:
        return k(low) if low == high else f"{k(low)}–{k(high)}"
    if low or high:
        return k(low or high)
    return None


class RemoteOKSource:
    name = "remoteok"
    complete_feed = False  # a rolling window of recent jobs, not every open job

    async def fetch(self, client: httpx.AsyncClient) -> list[FeedPage | Exception]:
        try:
            response = await client.get(API_URL)
            response.raise_for_status()
            return [FeedPage(self.name, "*", response.json())]
        except (httpx.HTTPError, ValueError) as exc:
            return [exc]

    def parse(self, page: FeedPage) -> list[RawJob]:
        jobs = []
        for item in page.payload:
            if "id" not in item or "position" not in item:  # the legal notice
                continue
            posted = None
            if item.get("epoch"):
                posted = datetime.fromtimestamp(int(item["epoch"]), tz=UTC)
            elif item.get("date"):
                posted = datetime.fromisoformat(item["date"])
            jobs.append(
                RawJob(
                    source=self.name,
                    source_id=str(item["id"]),
                    url=item.get("url") or f"https://remoteok.com/remote-jobs/{item['id']}",
                    title=item["position"],
                    company=item.get("company") or "Unknown",
                    location=(item.get("location") or "").strip() or None,
                    description_html=item.get("description") or "",
                    posted_at=posted,
                    salary=format_salary(item.get("salary_min"), item.get("salary_max")),
                    tags=list(item.get("tags") or []),
                    remote=True,
                )
            )
        return jobs
