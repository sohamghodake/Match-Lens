"""Fetch, normalize, de-duplicate, embed and store remote tech jobs.

    python -m ingestion.run                         # all sources, write to DATABASE_URL
    python -m ingestion.run --dry-run               # fetch and classify, write nothing
    python -m ingestion.run --sources greenhouse    # a subset
    python -m ingestion.run --save-raw DIR          # also keep the raw feeds
    python -m ingestion.run --replay DIR            # use saved feeds instead of the network
    python -m ingestion.run --llm-skills            # add the optional LLM skill pass

Runs daily on GitHub Actions (.github/workflows/ingest.yml). Every run is recorded in
ingestion_runs. Exits non-zero only if no source could be fetched at all.
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import IngestionRun
from app.db.retention import purge_expired_resumes
from app.db.session import get_sessionmaker
from app.llm.client import get_llm_client
from app.llm.embeddings import Embedder, get_embedder
from ingestion import store
from ingestion.dedupe import Deduper
from ingestion.llm_skills import enrich_skills
from ingestion.models import FeedPage
from ingestion.normalize import NormalizedJob, embedding_text, normalize
from ingestion.scrapers import Source, all_sources

log = logging.getLogger("ingestion")

USER_AGENT = "MatchLens/0.1 job aggregator (+https://github.com/sohamghodake/Match-Lens)"
WHOLE_SOURCE_FILE = "_all"  # saved-feed filename for scope "*"


@dataclass
class SourceStats:
    fetched: int = 0
    kept: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    duplicates: int = 0
    filtered: dict[str, int] = field(default_factory=dict)
    deactivated: int = 0
    pages_ok: int = 0
    pages_failed: int = 0


@dataclass
class RunResult:
    status: str
    stats: dict[str, SourceStats]
    errors: list[dict[str, str]]
    llm: dict[str, Any] | None
    seconds: float

    def totals(self) -> dict[str, int]:
        t = Counter()
        for s in self.stats.values():
            t.update(
                fetched=s.fetched, inserted=s.inserted, updated=s.updated,
                skipped=s.unchanged + s.duplicates + sum(s.filtered.values()),
            )  # fmt: skip
        return {"fetched": t["fetched"], "inserted": t["inserted"], "updated": t["updated"],
                "skipped": t["skipped"], "errors": len(self.errors)}  # fmt: skip


# ── fetching ──────────────────────────────────────────────────────────────────────


async def fetch_pages(
    sources: list[Source], replay: Path | None
) -> list[tuple[Source, FeedPage | Exception]]:
    if replay is not None:
        pages: list[tuple[Source, FeedPage | Exception]] = []
        for source in sources:
            for path in sorted((replay / source.name).glob("*.json")):
                scope = "*" if path.stem == WHOLE_SOURCE_FILE else path.stem
                pages.append((source, FeedPage(source.name, scope, json.loads(path.read_text()))))
        return pages

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(60, connect=15),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        transport=httpx.AsyncHTTPTransport(retries=2),  # retries connection failures
    ) as client:
        results = await asyncio.gather(*(s.fetch(client) for s in sources))
    return [
        (source, page) for source, pages in zip(sources, results, strict=True) for page in pages
    ]


def save_pages(pages: list[tuple[Source, FeedPage | Exception]], directory: Path) -> None:
    for _, page in pages:
        if isinstance(page, FeedPage):
            name = WHOLE_SOURCE_FILE if page.scope == "*" else page.scope
            target = directory / page.source / f"{name}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(page.payload))


# ── the run ───────────────────────────────────────────────────────────────────────


def _is_stale(job: NormalizedJob, now: datetime) -> bool:
    return job.posted_at is not None and job.posted_at < now - store.STALE_AFTER


async def run(
    source_names: list[str],
    *,
    session: AsyncSession,
    embedder: Embedder,
    dry_run: bool = False,
    replay: Path | None = None,
    save_raw: Path | None = None,
    llm_skills: bool = False,
    llm_max_jobs: int = 25,
    now: datetime | None = None,
) -> RunResult:
    started = time.perf_counter()
    now = now or datetime.now(UTC)
    available = all_sources()
    sources = [available[name] for name in source_names]
    stats = {s.name: SourceStats() for s in sources}
    errors: list[dict[str, str]] = []

    pages = await fetch_pages(sources, replay)
    if save_raw is not None:
        save_pages(pages, save_raw)

    # Parse and normalize.
    complete_scopes: list[tuple[str, str]] = []
    kept: list[NormalizedJob] = []
    for source, page in pages:
        st = stats[source.name]
        if isinstance(page, Exception):
            st.pages_failed += 1
            notes = " ".join(getattr(page, "__notes__", []))
            errors.append(
                {"source": source.name, "message": f"{type(page).__name__}: {page} {notes}".strip()}
            )
            continue
        try:
            raw_jobs = source.parse(page)
        except Exception as exc:  # a feed changed shape: log it, keep the other sources
            st.pages_failed += 1
            errors.append(
                {"source": source.name, "message": f"parse error in {page.scope}: {exc!r}"}
            )
            continue
        st.pages_ok += 1
        if source.complete_feed:
            complete_scopes.append((source.name, page.scope))
        st.fetched += len(raw_jobs)
        for raw in raw_jobs:
            result = normalize(raw)
            if not isinstance(result, str) and not source.complete_feed and _is_stale(result, now):
                result = "stale"  # rolling feeds keep old posts; don't store them
            if isinstance(result, str):
                st.filtered[result] = st.filtered.get(result, 0) + 1
            else:
                kept.append(result)
                st.kept += 1

    # Classify against the database.
    deduper = Deduper(await store.load_stored(session))
    new: list[NormalizedJob] = []
    changed: list[tuple[int, NormalizedJob]] = []
    unchanged_ids: list[int] = []
    seen_ids: set[tuple[str, str]] = set()
    for job in kept:
        if (job.source, job.source_id) in seen_ids:  # listed twice in one feed
            stats[job.source].duplicates += 1
            continue
        seen_ids.add((job.source, job.source_id))
        kind, job_id = deduper.classify(job)
        if kind == "new":
            new.append(job)
        elif kind == "changed":
            assert job_id is not None
            changed.append((job_id, job))
        elif kind == "unchanged":
            assert job_id is not None
            unchanged_ids.append(job_id)
            stats[job.source].unchanged += 1
        else:
            stats[job.source].duplicates += 1

    # Optional LLM skills, then embeddings, for new and changed jobs only.
    to_embed = new + [job for _, job in changed]
    llm_summary = None
    if llm_skills and to_embed:
        enrich = await enrich_skills(to_embed, get_llm_client(), max_jobs=llm_max_jobs)
        llm_summary = asdict(enrich)
    vectors = (
        await embedder.embed_documents([embedding_text(j) for j in to_embed]) if to_embed else []
    )
    vector_by_key = {(j.source, j.source_id): v for j, v in zip(to_embed, vectors, strict=True)}

    if not dry_run:
        inserted = await store.insert_jobs(
            session,
            [(j, vector_by_key[(j.source, j.source_id)]) for j in new],
            embedder.model_name,
            now,
        )
        await store.update_jobs(
            session,
            [(i, j, vector_by_key[(j.source, j.source_id)]) for i, j in changed],
            embedder.model_name,
            now,
        )
        await store.touch_jobs(session, unchanged_ids, now)
        for source_name, scope in complete_scopes:
            stats[source_name].deactivated += await store.deactivate_unseen(
                session, source_name, scope, now
            )
        for source in sources:
            if not source.complete_feed and stats[source.name].pages_ok:
                stats[source.name].deactivated += await store.deactivate_stale(
                    session, source.name, now
                )
        await session.commit()
        if inserted != len(new):  # only possible if another run inserted concurrently
            log.warning("expected %d inserts, database took %d", len(new), inserted)
    for job in new:
        stats[job.source].inserted += 1
    for _, job in changed:
        stats[job.source].updated += 1

    ok_pages = sum(s.pages_ok for s in stats.values())
    status = "failed" if ok_pages == 0 else ("partial" if errors else "success")
    return RunResult(status, stats, errors, llm_summary, time.perf_counter() - started)


def print_summary(result: RunResult, dry_run: bool) -> None:
    prefix = "DRY RUN, nothing written. " if dry_run else ""
    print(f"\n{prefix}status: {result.status} in {result.seconds:.1f} s")
    columns = ("fetched", "kept", "new", "changed", "same", "dupes", "closed")
    print(f"{'source':<11} " + " ".join(f"{c:>7}" for c in columns) + "  filtered")
    for name, s in result.stats.items():
        filtered = ", ".join(f"{k} {v}" for k, v in sorted(s.filtered.items())) or "-"
        print(
            f"{name:<11} "
            + " ".join(
                f"{n:>7}"
                for n in (
                    s.fetched,
                    s.kept,
                    s.inserted,
                    s.updated,
                    s.unchanged,
                    s.duplicates,
                    s.deactivated,
                )
            )
            + f"  {filtered}"
        )
    for err in result.errors:
        print(f"::warning::{err['source']}: {err['message']}")
    if result.llm:
        print(f"LLM skills: {result.llm}")


async def main_async(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    names = [n.strip() for n in args.sources.split(",") if n.strip()]
    unknown = set(names) - set(all_sources())
    if unknown:
        print(f"unknown sources: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2

    sessionmaker = get_sessionmaker()
    run_id = None
    if not args.dry_run:
        async with sessionmaker() as session:
            record = IngestionRun()
            session.add(record)
            await session.commit()
            run_id = record.id

    async with sessionmaker() as session:
        try:
            result = await run(
                names,
                session=session,
                embedder=get_embedder(),
                dry_run=args.dry_run,
                replay=args.replay,
                save_raw=args.save_raw,
                llm_skills=args.llm_skills or settings.ingest_llm_skills,
                llm_max_jobs=args.llm_max_jobs or settings.ingest_llm_max_jobs,
            )
        except Exception as exc:
            await session.rollback()
            if run_id is not None:
                await _finish(
                    sessionmaker,
                    run_id,
                    status="failed",
                    errors=[{"source": "run", "message": repr(exc)}],
                )
            raise

    print_summary(result, args.dry_run)
    if run_id is not None:
        await _finish(sessionmaker, run_id, result=result)
        async with sessionmaker() as session:
            purged = await purge_expired_resumes(session)
            if purged:
                print(f"deleted {purged} expired resumes")
    return 1 if result.status == "failed" else 0


async def _finish(
    sessionmaker: Any,
    run_id: int,
    *,
    result: RunResult | None = None,
    status: str | None = None,
    errors: list[dict[str, str]] | None = None,
) -> None:
    async with sessionmaker() as session:
        record = await session.get(IngestionRun, run_id)
        record.finished_at = datetime.now(UTC)
        if result is not None:
            for key, value in result.totals().items():
                setattr(record, key, value)
            record.status = result.status
            record.error_details = result.errors
            record.sources = {name: asdict(s) for name, s in result.stats.items()}
            if result.llm:
                record.sources["_llm_skills"] = result.llm
        else:
            record.status = status or "failed"
            record.error_details = errors or []
            record.errors = len(record.error_details)
        await session.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sources", default=",".join(all_sources()), help="comma-separated")
    parser.add_argument("--dry-run", action="store_true", help="fetch and classify only")
    parser.add_argument("--replay", type=Path, help="read feeds saved with --save-raw")
    parser.add_argument("--save-raw", type=Path, help="save fetched feeds to this directory")
    parser.add_argument("--llm-skills", action="store_true", help="add the LLM skill pass")
    parser.add_argument("--llm-max-jobs", type=int, help="cap for the LLM skill pass")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
