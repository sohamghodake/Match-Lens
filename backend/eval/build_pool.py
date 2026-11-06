"""Build the relevance-judging pool: for each resume, every ranking system's top 10.

    python -m eval.build_pool                       # all labeled sample + private resumes
    python -m eval.build_pool --docs private:me.pdf sample:alex_chen_backend.pdf
    python -m eval.build_pool --add-local           # also re-rank with local qwen2.5:3b (slow)

Systems compared (the plan's precision@10 table):
    vector          stage 1 only: nearest jobs by embedding
    hybrid          stage 2: similarity + skill coverage - seniority penalty
    rerank:<model>  stage 3: the LLM re-ranks the hybrid top 20

The pool is the union of their top 10s (standard IR pooling), judged once in /label/relevance,
then every system's precision@10 comes from the same judgments. Rankings and job details are
frozen into pool.json, so the numbers don't drift as jobs open and close.
Rebuilding replaces the pool; existing judgments are kept and reused where jobs repeat.
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.llm.client import LLMClient, LLMError
from app.llm.embeddings import get_embedder
from app.matching import rerank
from app.matching.retrieve import retrieve
from app.matching.schema import MatchFilters
from app.matching.score import score_candidates
from app.matching.service import _posting_key, _unique_postings
from app.parsing.service import embedding_text
from eval import store
from eval.runs import parsed_profile

K = 10


def _llm(base: LLMClient, model: str) -> LLMClient:
    # More retries than the app: a batch job can afford to wait out rate limits.
    return LLMClient(base_url=base.base_url, api_key=base.client.api_key, model=model,
                     max_retries=6, timeout=600)  # fmt: skip


async def build(doc_ids: list[str], rerank_models: list[str], local_model: str | None) -> dict:
    settings = get_settings()
    embedder = get_embedder()
    base = LLMClient.from_settings(settings)
    parser_llm = _llm(base, settings.llm_model)
    rerankers = {f"rerank:{m}": _llm(base, m) for m in rerank_models}
    if local_model:
        rerankers[f"rerank:{local_model}"] = LLMClient(
            base_url="http://host.docker.internal:11434/v1", api_key="ollama",
            model=local_model, timeout=900, max_retries=0,
        )  # fmt: skip

    pool: dict = {
        "created_at": datetime.now(UTC).isoformat(),
        "k": K,
        "systems": ["vector", "hybrid", *rerankers],
        "resumes": [],
        "jobs": {},
    }
    for doc_id in doc_ids:
        profile = await parsed_profile(doc_id, parser_llm)
        vector = await embedder.embed_query(embedding_text(profile))
        async with get_sessionmaker()() as session:
            candidates = await retrieve(
                session, vector, embed_model=embedder.model_name, filters=MatchFilters(),
                limit=settings.match_candidates, now=datetime.now(UTC),
            )  # fmt: skip
        jobs = {c.job.id: c.job for c in candidates}

        seen: set[str] = set()
        vector_run = []
        for c in sorted(candidates, key=lambda c: c.similarity, reverse=True):
            if (key := _posting_key(c.job)) not in seen:
                seen.add(key)
                vector_run.append(c.job.id)
        scored = _unique_postings(
            score_candidates(
                [(c.job.id, c.similarity, c.job.skills, c.job.seniority) for c in candidates],
                profile.skills,
                profile.seniority,
            ),
            jobs,
        )
        runs = {"vector": vector_run[:K], "hybrid": [s.job_id for s in scored[:K]]}

        top = scored[: settings.match_rerank_top]
        cards = [
            rerank.JobCard(i, jobs[s.job_id].title, jobs[s.job_id].company,
                           jobs[s.job_id].seniority, jobs[s.job_id].skills,
                           jobs[s.job_id].description)
            for i, s in enumerate(top, start=1)
        ]  # fmt: skip
        prompt = rerank.build_prompt(profile, cards)
        for name, llm in rerankers.items():
            try:
                result = await llm.structured(
                    prompt, rerank.RerankResult, system=rerank.SYSTEM_PROMPT,
                    reasoning_effort="low" if "gpt-oss" in llm.model else None,
                )  # fmt: skip
            except LLMError as exc:
                print(f"  {name} failed for {doc_id}: {exc}", file=sys.stderr)
                continue
            judged = rerank.merge(result, len(cards))
            # Same order as the app: the LLM's score, then the stage-2 score.
            order = sorted(
                range(1, len(top) + 1),
                key=lambda n: (n in judged, judged[n].score if n in judged else 0,
                               top[n - 1].hybrid),
                reverse=True,
            )  # fmt: skip
            runs[name] = [top[n - 1].job_id for n in order[:K]]

        pooled = sorted({job_id for run in runs.values() for job_id in run})
        for job_id in pooled:
            job = jobs[job_id]
            pool["jobs"][str(job_id)] = {
                "title": job.title, "company": job.company, "location": job.location,
                "url": job.url, "source": job.source, "seniority": job.seniority,
                "skills": job.skills[:15], "excerpt": rerank.snippet(job.description, 900),
            }  # fmt: skip
        pool["resumes"].append(
            {
                "key": doc_id,
                "profile": rerank.candidate_summary(profile),
                "runs": runs,
                "jobs": pooled,
            }
        )
        sizes = ", ".join(f"{name} {len(run)}" for name, run in runs.items())
        print(f"{doc_id}: {len(pooled)} jobs to judge ({sizes})")
    return pool


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--docs", nargs="*", help="document ids; default: all labeled resumes")
    parser.add_argument("--add-local", action="store_true", help="also re-rank with qwen2.5:3b")
    args = parser.parse_args()
    settings = get_settings()
    doc_ids = args.docs or [d.id for d in store.list_documents() if d.status == "verified"]
    if not doc_ids:
        print("No labeled resumes yet. Label some at /label, or pass --docs.")
        return 1
    models = list(dict.fromkeys([settings.llm_model, settings.llm_model_fast]))
    pool = asyncio.run(build(doc_ids, models, "qwen2.5:3b" if args.add_local else None))
    store.save_pool(pool)
    total = sum(len(r["jobs"]) for r in pool["resumes"])
    print(f"\nPool: {len(pool['resumes'])} resumes, {total} judgments needed.")
    print("Judge them at http://localhost:3100/label/relevance")
    return 0


if __name__ == "__main__":
    sys.exit(main())
