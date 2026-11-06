"""Send the same structured-output prompt to one or more LLM providers.

    python -m scripts.smoke_llm                          # the provider in LLM_* settings
    python -m scripts.smoke_llm -p ollama-cloud -p openai
    python -m scripts.smoke_llm -p ollama-local=gpt-oss:120b-cloud   # NAME=MODEL override
    python -m scripts.smoke_llm --all                    # every preset that has a key
    python -m scripts.smoke_llm --embeddings             # also check the embedder

Presets read keys from OPENAI_API_KEY and OLLAMA_API_KEY. Exits non-zero if any
provider fails, so it doubles as a CI or pre-deploy check.
"""

import argparse
import asyncio
import math
import sys
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.llm.client import LLMClient, LLMError
from app.llm.embeddings import get_embedder
from app.llm.providers import PRESETS

RESUME_SNIPPET = """\
Priya Raman, Backend Engineer
2021-present  Backend Engineer, Flowstack: Python, FastAPI and PostgreSQL services
              handling 2M requests a day; moved job processing from cron to Celery.
2019-2021     Software Engineer, Nimbus Labs: Django REST APIs, Redis caching,
              Docker and GitHub Actions CI.
"""

PROMPT = (
    "Extract the candidate's technical skills (canonical names), their seniority level "
    "and total years of professional experience as of 2026 from this resume:\n\n" + RESUME_SNIPPET
)


class SmokeProfile(BaseModel):
    skills: list[str] = Field(min_length=3)
    seniority: Literal["junior", "mid", "senior", "lead"]
    years_experience: float = Field(ge=0, le=60)


@dataclass
class Target:
    label: str
    base_url: str
    api_key: str | None
    model: str


def resolve_targets(args: argparse.Namespace) -> list[Target]:
    settings = get_settings()
    specs: list[str] = list(args.provider or [])
    if args.all:
        specs += [name for name, preset in PRESETS.items() if preset.api_key()]
    if not specs:
        return [
            Target(
                "active (LLM_*)",
                settings.llm_base_url,
                settings.llm_api_key.get_secret_value(),
                settings.llm_model,
            )
        ]
    targets = []
    for spec in dict.fromkeys(specs):  # dedupe, keep order
        name, _, model = spec.partition("=")
        if name not in PRESETS:
            sys.exit(f"unknown provider {name!r}; choose from {', '.join(PRESETS)}")
        preset = PRESETS[name]
        targets.append(
            Target(name, preset.base_url, preset.api_key(), model or preset.default_model)
        )
    return targets


async def check(target: Target) -> bool:
    print(f"\n▶ {target.label}: {target.model} at {target.base_url}")
    if not target.api_key:
        print("  ✗ skipped: no API key (set the provider's *_API_KEY variable)")
        return False
    client = LLMClient(
        base_url=target.base_url, api_key=target.api_key, model=target.model, max_retries=0
    )
    try:
        result = await client.structured_detailed(PROMPT, SmokeProfile)
    except LLMError as exc:
        print(f"  ✗ {exc}")
        return False
    tokens = (
        f"{result.prompt_tokens} in / {result.completion_tokens} out"
        if result.prompt_tokens is not None
        else "not reported"
    )
    repaired = " (after repair retry)" if result.attempts > 1 else ""
    print(f"  ✓ valid JSON{repaired} in {result.latency_ms} ms, tokens: {tokens}")
    print(f"    {result.value.model_dump_json()}")
    return True


async def check_embeddings() -> bool:
    embedder = get_embedder()
    print(f"\n▶ embeddings: {embedder.model_name}")
    try:
        query = await embedder.embed_query("Senior Python backend engineer, FastAPI, PostgreSQL")
        docs = await embedder.embed_documents(
            [
                "We're hiring a backend engineer to build Python APIs on FastAPI and Postgres.",
                "Pastry chef wanted for a busy bakery; early mornings, croissants and tarts.",
            ]
        )
    except Exception as exc:
        print(f"  ✗ {type(exc).__name__}: {exc}")
        return False
    related, unrelated = (_cosine(query, doc) for doc in docs)
    ok = related > unrelated
    mark = "✓" if ok else "✗"
    print(
        f"  {mark} {len(query)}-d; cosine to related job {related:.3f}, unrelated {unrelated:.3f}"
    )
    return ok


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "-p",
        "--provider",
        action="append",
        metavar="NAME[=MODEL]",
        help=f"preset to test: {', '.join(PRESETS)} (repeatable)",
    )
    parser.add_argument("--all", action="store_true", help="test every preset that has a key")
    parser.add_argument("--embeddings", action="store_true", help="also check the embedder")
    args = parser.parse_args()

    results = [await check(target) for target in resolve_targets(args)]
    if args.embeddings:
        results.append(await check_embeddings())
    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
