"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { errorMessage } from "@/lib/api";
import { evalApi, toolsDisabled, type Grade, type Pool } from "@/lib/evalApi";

const GRADES: { value: Grade; label: string; active: string }[] = [
  { value: 0, label: "Not a fit", active: "bg-zinc-700 text-white dark:bg-zinc-300 dark:text-zinc-900" },
  { value: 1, label: "Partly", active: "bg-amber-500 text-white" },
  { value: 2, label: "Good fit", active: "bg-emerald-600 text-white" },
];

/** A stable order that hides which system ranked a job where (FNV-1a hash). */
function blindOrder(resumeKey: string, jobs: number[]): number[] {
  const hash = (s: string) => {
    let h = 2166136261;
    for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
    return h >>> 0;
  };
  return [...jobs].sort((a, b) => hash(`${resumeKey}:${a}`) - hash(`${resumeKey}:${b}`));
}

export function RelevanceLabeler() {
  const [pool, setPool] = useState<Pool | null | undefined>(undefined);
  const [judgments, setJudgments] = useState<Record<string, Record<string, Grade>>>({});
  const [current, setCurrent] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    evalApi.relevance().then(
      (state) => {
        if (cancelled) return;
        setPool(state.pool);
        setJudgments(state.judgments);
      },
      (err: unknown) => {
        if (!cancelled) setError(toolsDisabled(err) ? "The labeling tools are off (EVAL_TOOLS)." : errorMessage(err));
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const resume = pool?.resumes[current];
  const order = useMemo(() => (resume ? blindOrder(resume.key, resume.jobs) : []), [resume]);

  if (error) return <p role="alert" className="text-sm text-red-700 dark:text-red-400">{error}</p>;
  if (pool === undefined) return <p className="text-sm text-zinc-500">Loading…</p>;
  if (pool === null || !resume) {
    return (
      <div className="space-y-2 text-sm">
        <p>No pool yet. Label some resumes, then run:</p>
        <pre className="rounded bg-zinc-100 p-2 dark:bg-zinc-900">docker compose exec backend python -m eval.build_pool</pre>
        <Link href="/label" className="text-emerald-700 hover:underline dark:text-emerald-400">← Labeling</Link>
      </div>
    );
  }

  const mine = judgments[resume.key] ?? {};
  const done = (key: string, jobs: number[]) => jobs.filter((j) => (judgments[key] ?? {})[String(j)] !== undefined).length;

  async function judge(jobId: number, grade: Grade) {
    if (!resume) return;
    const next = mine[String(jobId)] === grade ? null : grade; // clicking again clears
    const before = judgments;
    const updated = { ...mine };
    if (next === null) delete updated[String(jobId)];
    else updated[String(jobId)] = next;
    setJudgments({ ...judgments, [resume.key]: updated }); // optimistic
    try {
      await evalApi.judge(resume.key, jobId, next);
    } catch (err) {
      setJudgments(before);
      setError(errorMessage(err));
    }
  }

  return (
    <div className="space-y-5">
      <header className="space-y-2">
        <Link href="/label" className="text-sm text-zinc-500 hover:underline">← Labeling</Link>
        <h1 className="text-2xl font-semibold tracking-tight">Job relevance</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Would this candidate be a reasonable applicant for each job? Judge skills and level; ignore
          location. Jobs are shuffled and show no scores, so no ranking system is favored.
        </p>
        <div className="flex flex-wrap gap-1.5">
          {pool.resumes.map((r, i) => {
            const n = done(r.key, r.jobs);
            return (
              <button key={r.key} type="button" onClick={() => setCurrent(i)} aria-pressed={i === current}
                className={`rounded-full border px-2.5 py-0.5 text-xs ${i === current ? "border-emerald-600 bg-emerald-600 text-white" : "border-zinc-300 dark:border-zinc-700"}`}>
                {r.key.split(":")[1]} · {n}/{r.jobs.length}
              </button>
            );
          })}
        </div>
      </header>

      <pre className="whitespace-pre-wrap rounded-lg border border-zinc-200 bg-white p-3 text-xs dark:border-zinc-800 dark:bg-zinc-900">
        {resume.profile}
      </pre>

      <ol className="space-y-3">
        {order.map((jobId) => {
          const job = pool.jobs[String(jobId)];
          const grade = mine[String(jobId)];
          return (
            <li key={jobId} className="space-y-2 rounded-xl border border-zinc-200 bg-white p-4 text-sm dark:border-zinc-800 dark:bg-zinc-900">
              <div>
                <p className="font-medium">{job.title}{job.seniority ? ` (${job.seniority})` : ""}</p>
                <p className="text-zinc-600 dark:text-zinc-400">{job.company}{job.location ? ` · ${job.location}` : ""}</p>
              </div>
              {job.skills.length > 0 && <p className="text-xs text-zinc-500">{job.skills.join(" · ")}</p>}
              <p className="text-xs leading-relaxed text-zinc-700 dark:text-zinc-300">{job.excerpt}</p>
              <div className="flex flex-wrap items-center gap-2">
                {GRADES.map((g) => (
                  <button key={g.value} type="button" onClick={() => judge(jobId, g.value)} aria-pressed={grade === g.value}
                    className={`rounded-md border px-3 py-1 text-sm ${grade === g.value ? `${g.active} border-transparent` : "border-zinc-300 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"}`}>
                    {g.label}
                  </button>
                ))}
                <a href={job.url} target="_blank" rel="noopener" className="ml-auto text-xs text-zinc-500 hover:underline">Full posting ↗</a>
              </div>
            </li>
          );
        })}
      </ol>
      {current < pool.resumes.length - 1 && (
        <button type="button" onClick={() => setCurrent(current + 1)} className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white">
          Next resume →
        </button>
      )}
    </div>
  );
}
