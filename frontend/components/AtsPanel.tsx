"use client";

import { useEffect, useState } from "react";

import { api, errorMessage, type AtsKeyword, type AtsReport } from "@/lib/api";

const MIN_DESCRIPTION = 50;

type State =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ok"; report: AtsReport }
  | { kind: "error"; message: string };

function verdict(score: number): { label: string; color: string } {
  if (score >= 80) return { label: "Strong match", color: "text-emerald-700 dark:text-emerald-400" };
  if (score >= 60) return { label: "Fair match", color: "text-amber-700 dark:text-amber-400" };
  return { label: "Needs work", color: "text-red-700 dark:text-red-400" };
}

function KeywordChips({ keywords }: { keywords: AtsKeyword[] }) {
  const found = keywords.filter((k) => k.status === "found");
  const synonyms = keywords.filter((k) => k.status === "synonym");
  const missing = keywords
    .filter((k) => k.status === "missing")
    .sort((a, b) => (a.importance === b.importance ? 0 : a.importance === "required" ? -1 : 1));
  const chip = "rounded border px-1.5 py-0.5 text-xs";
  return (
    <div className="space-y-2 text-sm">
      {found.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-zinc-500">In your resume</span>
          {found.map((k) => (
            <span key={k.keyword} className={`${chip} border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-100`}>
              {k.keyword}
            </span>
          ))}
        </div>
      )}
      {synonyms.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-zinc-500">Different wording</span>
          {synonyms.map((k) => (
            <span key={k.keyword} className={`${chip} border-sky-200 bg-sky-50 text-sky-900 dark:border-sky-900 dark:bg-sky-950/50 dark:text-sky-100`}>
              {k.keyword} ≈ {k.resume_term}
            </span>
          ))}
        </div>
      )}
      {missing.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-zinc-500">Missing</span>
          {missing.map((k) => (
            <span key={k.keyword} className={`${chip} border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100`}>
              {k.keyword}
              {k.importance === "preferred" ? " (nice to have)" : ""}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function Report({ report }: { report: AtsReport }) {
  const v = verdict(report.score);
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-4xl font-semibold tabular-nums">{Math.round(report.score)}</span>
        <span className="text-zinc-500">/ 100</span>
        <span className={`font-medium ${v.color}`}>{v.label}</span>
        {report.job.title && (
          <span className="w-full text-sm text-zinc-500">
            against “{report.job.title}”
            {report.analysis_method === "rules" ? " (AI unavailable; checked with rules)" : ""}
          </span>
        )}
      </div>

      <KeywordChips keywords={report.keywords} />

      <ul className="space-y-4">
        {report.parts.map((part) => (
          <li key={part.key} className="space-y-1.5">
            <div className="flex items-baseline justify-between text-sm">
              <span className="font-medium">{part.name}</span>
              <span className="tabular-nums text-zinc-500">
                {part.points} / {part.max_points}
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800" aria-hidden>
              <div
                className="h-full rounded-full bg-emerald-600"
                style={{ width: `${(100 * part.points) / part.max_points}%` }}
              />
            </div>
            {part.deductions.length > 0 && (
              <ul className="space-y-1 pt-1 text-sm">
                {part.deductions.map((d, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="w-12 shrink-0 tabular-nums text-red-700 dark:text-red-400">
                      −{d.points}
                    </span>
                    <span>
                      {d.reason} <span className="text-zinc-500">{d.suggestion}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {part.notes.map((note, i) => (
              <p key={i} className="flex gap-2 text-sm text-zinc-500">
                <span className="w-12 shrink-0">Tip</span>
                <span>{note.message}</span>
              </p>
            ))}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Paste a job description, or pass a stored job (`jobId`) to score immediately. */
export function AtsPanel({ resumeId, jobId }: { resumeId: string; jobId?: number }) {
  const [text, setText] = useState("");
  const [state, setState] = useState<State>(jobId ? { kind: "loading" } : { kind: "idle" });

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    api.ats(resumeId, { jobId }).then(
      (report) => {
        if (!cancelled) setState({ kind: "ok", report });
      },
      (err: unknown) => {
        if (!cancelled) setState({ kind: "error", message: errorMessage(err) });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [resumeId, jobId]);

  async function check() {
    setState({ kind: "loading" });
    try {
      setState({ kind: "ok", report: await api.ats(resumeId, { jobDescription: text }) });
    } catch (err) {
      setState({ kind: "error", message: errorMessage(err) });
    }
  }

  const tooShort = text.trim().length < MIN_DESCRIPTION;
  return (
    <div className="space-y-4">
      {!jobId && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!tooShort) void check();
          }}
          className="space-y-2"
        >
          <label htmlFor="jd" className="text-sm text-zinc-600 dark:text-zinc-400">
            Paste a job description to see how an applicant tracking system would score your
            resume against it.
          </label>
          <textarea
            id="jd"
            value={text}
            onChange={(event) => setText(event.target.value)}
            rows={6}
            maxLength={20_000}
            placeholder="Job title, responsibilities, requirements…"
            className="w-full rounded-lg border border-zinc-300 bg-white p-3 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          />
          <button
            type="submit"
            disabled={tooShort || state.kind === "loading"}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            {state.kind === "loading" ? "Checking…" : "Check ATS score"}
          </button>
        </form>
      )}
      {state.kind === "loading" && jobId && (
        <p className="text-sm text-zinc-500">Reading the job description…</p>
      )}
      {state.kind === "error" && (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950/50 dark:text-red-200">
          {state.message}
        </p>
      )}
      {state.kind === "ok" && <Report report={state.report} />}
    </div>
  );
}
