"""Parse the labeled sample resumes with the configured LLM and score each field.

    python -m eval.parse_eval                    # all resumes in eval/samples/labels.json
    python -m eval.parse_eval --file my.pdf      # parse one file and print the profile
    python -m eval.parse_eval --json out.json    # also save per-resume results

The provider comes from LLM_* settings, e.g.
    LLM_MODEL=gpt-oss:120b-cloud python -m eval.parse_eval

Phase 2's exit check is "no missing roles or dates": every labeled role found, with
its start and end dates exactly right. Field accuracy (title, company, start, end)
is the number the Phase 6 results table builds on.
"""

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.llm.client import get_llm_client
from app.parsing.extract import extract
from app.parsing.redact import redact_contacts
from app.parsing.schema import ResumeProfile, Role
from app.parsing.service import ParsedResume, parse_resume

SAMPLES = Path(__file__).parent / "samples"
ROLE_FIELDS = ("title", "company", "start", "end")


def _norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _similar(a: str | None, b: str | None) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def match_roles(expected: list[dict[str, str]], found: list[Role]) -> list[Role | None]:
    """Pair each labeled role with the most similar parsed role (each used once)."""
    remaining = list(found)
    pairs: list[Role | None] = []
    for exp in expected:
        best, best_score = None, 0.0
        for role in remaining:
            score = _similar(exp["title"], role.title) + _similar(exp["company"], role.company)
            score += 0.5 * (exp["start"] == role.start)
            if score > best_score:
                best, best_score = role, score
        if best is not None and best_score >= 1.2:
            remaining.remove(best)
            pairs.append(best)
        else:
            pairs.append(None)
    return pairs


def score_resume(label: dict[str, Any], profile: ResumeProfile) -> dict[str, Any]:
    pairs = match_roles(label["roles"], profile.roles)
    correct = {f: 0 for f in ROLE_FIELDS}
    problems = []
    for exp, got in zip(label["roles"], pairs, strict=True):
        name = f"{exp['title']} @ {exp['company']}"
        if got is None:
            problems.append(f"missing role: {name}")
            continue
        for field in ("title", "company"):
            if _similar(exp[field], getattr(got, field)) >= 0.85:
                correct[field] += 1
            else:
                problems.append(f"{field} for {name}: got {getattr(got, field)!r}")
        for field in ("start", "end"):
            if exp[field] == getattr(got, field):
                correct[field] += 1
            else:
                problems.append(
                    f"{field} for {name}: expected {exp[field]}, got {getattr(got, field)}"
                )
    extra = len(profile.roles) - sum(p is not None for p in pairs)
    if extra:
        problems.append(f"{extra} extra role(s) not in the labels")

    found_skills = {s.lower() for s in profile.skills}
    missing_skills = [s for s in label["skills"] if s.lower() not in found_skills]
    return {
        "roles_expected": len(label["roles"]),
        "roles_found": sum(p is not None for p in pairs),
        "field_correct": correct,
        "field_total": len(label["roles"]),
        "dates_ok": correct["start"] == correct["end"] == len(label["roles"]),
        "skills_recall": 1 - len(missing_skills) / len(label["skills"]),
        "missing_skills": missing_skills,
        "seniority_expected": label["seniority"],
        "seniority_found": profile.seniority,
        "problems": problems,
    }


async def parse_file(path: Path) -> tuple[ParsedResume, dict[str, Any], float]:
    extracted = extract(await asyncio.to_thread(path.read_bytes))
    redacted = redact_contacts(extracted.text)
    started = time.perf_counter()
    parsed = await parse_resume(redacted.text, get_llm_client(), today=date.today())
    meta = {"kind": extracted.kind, "columns": extracted.columns, "tables": extracted.tables}
    return parsed, meta, time.perf_counter() - started


async def show_one(path: Path) -> int:
    parsed, meta, seconds = await parse_file(path)
    print(f"{path.name}: {meta}, parsed by {parsed.method} in {seconds:.1f} s\n")
    print(parsed.profile.model_dump_json(indent=2))
    for warning in parsed.warnings:
        print(f"⚠ {warning}")
    return 0


async def evaluate(json_out: Path | None) -> int:
    labels = json.loads((SAMPLES / "labels.json").read_text())
    settings = get_settings()
    print(f"model: {settings.llm_model} at {settings.llm_base_url}\n")
    results, totals = [], {f: 0 for f in ROLE_FIELDS}
    total_roles = 0
    for label in labels:
        parsed, meta, seconds = await parse_file(SAMPLES / label["file"])
        result = score_resume(label, parsed.profile)
        result |= {"file": label["file"], "method": parsed.method, "seconds": round(seconds, 1)}
        results.append(result)
        total_roles += result["field_total"]
        for f in ROLE_FIELDS:
            totals[f] += result["field_correct"][f]

        status = (
            "PASS"
            if result["roles_found"] == result["roles_expected"] and result["dates_ok"]
            else "FAIL"
        )
        roles = f"{result['roles_found']}/{result['roles_expected']}"
        print(
            f"{status}  {label['file']:<28} roles {roles}"
            f"  skills {result['skills_recall']:.0%}"
            f"  seniority {result['seniority_found']} (label {result['seniority_expected']})"
            f"  [{parsed.method}, {seconds:.1f} s]"
        )
        for problem in result["problems"]:
            print(f"      - {problem}")
        if result["missing_skills"]:
            print(f"      - skills not found: {', '.join(result['missing_skills'])}")

    print("\nfield accuracy over", total_roles, "roles:")
    for f in ROLE_FIELDS:
        print(f"  {f:<8} {totals[f] / total_roles:.0%}")
    overall = sum(totals.values()) / (total_roles * len(ROLE_FIELDS))
    print(f"  overall  {overall:.1%}")
    seniority_hits = sum(r["seniority_found"] == r["seniority_expected"] for r in results)
    print(f"seniority matches label: {seniority_hits}/{len(results)} (labels are judgment calls)")

    if json_out:
        payload = json.dumps({"model": settings.llm_model, "results": results}, indent=2)
        await asyncio.to_thread(json_out.write_text, payload)
        print(f"\nwrote {json_out}")
    passed = all(r["roles_found"] == r["roles_expected"] and r["dates_ok"] for r in results)
    print(f"\nexit check (no missing roles or dates): {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--file", type=Path, help="parse a single resume and print it")
    parser.add_argument("--json", type=Path, help="write per-resume results to this file")
    args = parser.parse_args()
    if args.file:
        return asyncio.run(show_one(args.file))
    return asyncio.run(evaluate(args.json))


if __name__ == "__main__":
    sys.exit(main())
