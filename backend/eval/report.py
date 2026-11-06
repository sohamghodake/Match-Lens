"""The Phase 6 results: parser accuracy and ranking precision, as a markdown table.

    python -m eval.report                                  # parser (LLM_MODEL) + ranking
    python -m eval.report --parse-models openai/gpt-oss-120b openai/gpt-oss-20b
    python -m eval.report --local                          # also local qwen2.5:3b (slow)
    python -m eval.report --write                          # also write eval/results.md

Parser accuracy uses every verified label (samples + yours). Ranking precision uses the
pool from eval.build_pool and your judgments: precision@10 counts "good fit" (2) as
relevant, and the lenient column counts "partly" (1) too. Only fully judged resumes count.
"""

import argparse
import asyncio
import statistics
import sys
from collections import defaultdict
from datetime import UTC, datetime

from app.core.config import get_settings
from app.llm.client import LLMClient
from eval import store
from eval.parse_eval import ROLE_FIELDS, score_resume
from eval.runs import parsed_profile

RESULTS = store.ROOT / "results.md"


def precision_at_k(ranking: list[int], grades: dict[str, int], k: int, threshold: int) -> float:
    return sum(1 for job in ranking[:k] if grades.get(str(job), 0) >= threshold) / k


def ranking_table(pool: dict | None, judgments: dict[str, dict[str, int]]) -> tuple[str, int]:
    if not pool:
        return "No relevance pool yet (`python -m eval.build_pool`).", 0
    k = pool["k"]
    done = [
        r for r in pool["resumes"] if all(str(j) in judgments.get(r["key"], {}) for j in r["jobs"])
    ]
    if not done:
        judged = sum(len(judgments.get(r["key"], {})) for r in pool["resumes"])
        needed = sum(len(r["jobs"]) for r in pool["resumes"])
        return f"No resume fully judged yet ({judged}/{needed} judgments).", 0
    rows = [f"| System | Precision@{k} (good fit) | Precision@{k} (good or partly) |",
            "| --- | --- | --- |"]  # fmt: skip
    for system in pool["systems"]:
        resumes = [r for r in done if system in r["runs"]]
        if not resumes:
            continue
        strict = statistics.mean(
            precision_at_k(r["runs"][system], judgments[r["key"]], k, 2) for r in resumes
        )
        lenient = statistics.mean(
            precision_at_k(r["runs"][system], judgments[r["key"]], k, 1) for r in resumes
        )
        rows.append(f"| {system} | {strict:.2f} | {lenient:.2f} |")
    return "\n".join(rows), len(done)


async def parser_table(models: list[str], local: bool) -> tuple[str, int]:
    labels = store.verified_labels()
    if not labels:
        return "No verified labels.", 0
    settings = get_settings()
    base = LLMClient.from_settings(settings)
    clients = {m: LLMClient(base_url=base.base_url, api_key=base.client.api_key, model=m,
                            max_retries=6, timeout=600) for m in models}  # fmt: skip
    if local:
        clients["qwen2.5:3b (local)"] = LLMClient(
            base_url="http://host.docker.internal:11434/v1", api_key="ollama",
            model="qwen2.5:3b", timeout=900, max_retries=0,
        )  # fmt: skip

    header = ["Model", "Resumes", "Roles found", *(f.capitalize() for f in ROLE_FIELDS),
              "Overall", "Skills recall", "Seniority"]  # fmt: skip
    rows = ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
    for name, llm in clients.items():
        totals: dict[str, int] = defaultdict(int)
        found = expected = seniority_hits = seniority_total = 0
        recalls = []
        for doc_id, label in labels.items():
            profile = await parsed_profile(doc_id, llm)
            result = score_resume(label.model_dump(), profile)
            for field in ROLE_FIELDS:
                totals[field] += result["field_correct"][field]
            found += result["roles_found"]
            expected += result["roles_expected"]
            if label.skills:
                recalls.append(result["skills_recall"])
            if label.seniority:
                seniority_total += 1
                seniority_hits += result["seniority_found"] == label.seniority
        n_roles = max(expected, 1)
        fields = [totals[f] / n_roles for f in ROLE_FIELDS]
        recall = f"{statistics.mean(recalls):.0%}" if recalls else "n/a"
        rows.append(
            f"| {name} | {len(labels)} | {found}/{expected} | "
            + " | ".join(f"{v:.0%}" for v in fields)
            + f" | {statistics.mean(fields):.1%} | {recall} | {seniority_hits}/{seniority_total} |"
        )
    return "\n".join(rows), len(labels)


async def run(models: list[str], local: bool, write: bool) -> int:
    parser_md, n_resumes = await parser_table(models, local)
    ranking_md, n_ranked = ranking_table(store.load_pool(), store.load_judgments())
    report = (
        f"## Results ({datetime.now(UTC):%d %b %Y})\n\n"
        f"### Resume parsing ({n_resumes} labeled resumes)\n\n{parser_md}\n\n"
        f"### Ranking ({n_ranked} fully judged resumes)\n\n{ranking_md}\n"
    )
    print(report)
    if write:
        RESULTS.write_text(report)
        print(f"wrote {RESULTS}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    settings = get_settings()
    parser.add_argument("--parse-models", nargs="*", default=[settings.llm_model])
    parser.add_argument("--local", action="store_true", help="also local qwen2.5:3b")
    parser.add_argument("--write", action="store_true", help="write eval/results.md")
    args = parser.parse_args()
    return asyncio.run(run(args.parse_models, args.local, args.write))


if __name__ == "__main__":
    sys.exit(main())
