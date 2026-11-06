"""Compare the free dictionary skill scan with an LLM on stored job descriptions.

    python -m eval.job_skills_eval --n 8                       # model from LLM_MODEL_FAST
    LLM_MODEL=qwen2.5:3b python -m eval.job_skills_eval --n 8

For each job: seconds per call, skills the LLM added beyond the dictionary, and how many
of those additions actually appear in the description ("grounded"). An addition that
isn't in the text is a hallucination. Read-only: nothing is written to the database.
"""

import argparse
import asyncio
import random
import statistics
import sys
import time

from sqlalchemy import select

from app.db.models import Job
from app.db.session import get_sessionmaker
from app.llm.client import LLMError, get_llm_client
from app.parsing.skills import normalize_skills
from ingestion.llm_skills import MAX_DESCRIPTION_CHARS, PROMPT, JobSkills, mentioned_in

grounded = mentioned_in  # the same check the pipeline applies


async def main(n: int, seed: int) -> int:
    llm = get_llm_client()
    async with get_sessionmaker()() as session:
        jobs = list(await session.scalars(select(Job).where(Job.is_active)))
    if not jobs:
        print("no active jobs; run `python -m ingestion.run` first")
        return 1
    sample = random.Random(seed).sample(jobs, min(n, len(jobs)))
    print(f"model: {llm.model_fast} at {llm.base_url}; {len(sample)} jobs\n")

    seconds, added_total, grounded_total, missed_total, failures = [], 0, 0, 0, 0
    for job in sample:
        text = job.description[:MAX_DESCRIPTION_CHARS]
        started = time.perf_counter()
        try:
            result = await llm.structured(
                PROMPT.format(title=job.title, description=text), JobSkills, fast=True
            )
        except LLMError as exc:
            failures += 1
            print(f"✗ {job.title[:50]} — {str(exc)[:120]}")
            continue
        took = time.perf_counter() - started
        seconds.append(took)
        llm_skills = normalize_skills([*result.required, *result.nice_to_have])
        rules = {s.lower() for s in job.skills}
        added = [s for s in llm_skills if s.lower() not in rules]
        ok = [s for s in added if grounded(s, f"{job.title}\n{text}")]
        missed = [s for s in job.skills if s.lower() not in {x.lower() for x in llm_skills}]
        added_total += len(added)
        grounded_total += len(ok)
        missed_total += len(missed)
        print(f"{took:5.1f} s  {job.title[:58]}")
        print(f"         dictionary: {', '.join(job.skills) or '-'}")
        print(f"         LLM added:  {', '.join(added) or '-'}")
        not_in_text = [s for s in added if s not in ok]
        if not_in_text:
            print(f"         not in text: {', '.join(not_in_text)}")

    if seconds:
        share = f" ({grounded_total / added_total:.0%})" if added_total else ""
        median = statistics.median(seconds)
        print(
            f"\n{len(seconds)} ok, {failures} failed | median {median:.1f} s/job"
            f" | LLM added {added_total} skills, {grounded_total} found in the text{share}"
        )
        print(f"dictionary skills the LLM didn't list: {missed_total}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--n", type=int, default=8)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.n, args.seed)))
