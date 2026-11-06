"""Greenhouse job board API (public, no key): one feed per company board.

    GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true

Each board lists every open job, so a job missing from a successfully fetched board is
closed. Boards were picked on 6 Nov 2026 from companies with public boards that list
remote roles; edit BOARDS to change the list.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime

import httpx

from ingestion.models import FeedPage, RawJob

API_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
CONCURRENCY = 4


@dataclass(frozen=True)
class Board:
    token: str
    # For distributed-by-default companies whose locations are just countries
    # ("United States"): treat every job as remote.
    remote_by_default: bool = False


BOARDS = [
    Board("samsara"), Board("gitlab"), Board("affirm"), Board("coinbase"),
    Board("grafanalabs"), Board("reddit"), Board("twilio"), Board("stripe"),
    Board("mozilla"), Board("instacart"), Board("databricks"), Board("pinterest"),
    Board("anthropic"), Board("datadog"), Board("fivetran"), Board("dropbox"),
    Board("airbnb"), Board("discord"), Board("gusto"), Board("planetscale"),
    Board("cloudflare"), Board("elastic", remote_by_default=True), Board("netlify"),
    Board("vercel"), Board("asana"), Board("airtable"), Board("cockroachlabs"),
    Board("duolingo"), Board("chime"),
]  # fmt: skip


class GreenhouseSource:
    name = "greenhouse"
    complete_feed = True

    def __init__(self, boards: list[Board] | None = None) -> None:
        self.boards = {b.token: b for b in (boards or BOARDS)}

    async def fetch(self, client: httpx.AsyncClient) -> list[FeedPage | Exception]:
        semaphore = asyncio.Semaphore(CONCURRENCY)

        async def one(token: str) -> FeedPage | Exception:
            async with semaphore:
                try:
                    response = await client.get(API_URL.format(token=token))
                    response.raise_for_status()
                    return FeedPage(self.name, token, response.json())
                except (httpx.HTTPError, ValueError) as exc:
                    exc.add_note(f"board={token}")
                    return exc

        return list(await asyncio.gather(*(one(token) for token in self.boards)))

    def parse(self, page: FeedPage) -> list[RawJob]:
        board = self.boards.get(page.scope, Board(page.scope))
        jobs = []
        for item in page.payload.get("jobs", []):
            published = item.get("first_published") or item.get("updated_at")
            jobs.append(
                RawJob(
                    source=self.name,
                    source_id=f"{board.token}:{item['id']}",
                    url=item["absolute_url"],
                    title=item["title"].strip(),
                    company=item.get("company_name") or board.token.title(),
                    location=((item.get("location") or {}).get("name") or "").strip() or None,
                    # Greenhouse returns the HTML entity-escaped; normalize unescapes it.
                    description_html=item.get("content") or "",
                    posted_at=datetime.fromisoformat(published) if published else None,
                    remote=True if board.remote_by_default else None,
                )
            )
        return jobs
