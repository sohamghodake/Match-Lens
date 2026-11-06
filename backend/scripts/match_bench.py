"""End-to-end matching latency per LLM provider, for one stored resume.

    python -m scripts.match_bench RESUME_ID -p groq -p groq=openai/gpt-oss-20b -p ollama-local

Each run skips the cache (refresh) and reports stage timings, tokens and the top 5.
Providers come from app/llm/providers.py presets; NAME=MODEL overrides the model.
"""

import argparse
import asyncio
import sys
import uuid

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Resume
from app.db.session import get_sessionmaker
from app.llm.client import LLMClient
from app.llm.embeddings import get_embedder
from app.llm.providers import PRESETS
from app.matching.schema import MatchFilters
from app.matching.service import find_matches


async def main(resume_id: uuid.UUID, specs: list[str]) -> int:
    base = get_settings()
    embedder = get_embedder()
    for spec in specs:
        name, _, model = spec.partition("=")
        preset = PRESETS[name]
        key = preset.api_key()
        if not key:
            print(f"\n▶ {spec}: skipped, {preset.api_key_env} not set")
            continue
        model = model or preset.default_model
        llm = LLMClient(base_url=preset.base_url, api_key=key, model=model, timeout=600)
        # reasoning_effort is a gpt-oss/OpenAI parameter; local models don't take it.
        settings = base.model_copy(
            update={
                "match_reasoning_effort": base.match_reasoning_effort
                if "gpt-oss" in model
                else None
            }
        )
        async with get_sessionmaker()() as session:
            resume = await session.scalar(select(Resume).where(Resume.id == resume_id))
            if resume is None:
                print("resume not found")
                return 1
            result = await find_matches(
                session, resume, llm=llm, embedder=embedder, settings=settings,
                filters=MatchFilters(), refresh=True, store=False,
            )  # fmt: skip
        t = result.timings
        print(f"\n▶ {name}: {model}")
        print(
            f"  total {t.total_ms / 1000:.1f} s (retrieve {t.retrieve_ms} ms, re-rank "
            f"{t.rerank_ms / 1000:.1f} s) | tokens {result.tokens} | re-ranked: {result.reranked}"
            + (f" | {result.note}" if result.note else "")
        )
        for m in result.matches[:5]:
            print(f"  {m.score:>3}  {m.job.title[:60]} ({m.job.company})")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("resume_id", type=uuid.UUID)
    parser.add_argument("-p", "--provider", action="append", required=True, metavar="NAME[=MODEL]")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.resume_id, args.provider)))
