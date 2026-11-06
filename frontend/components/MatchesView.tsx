"use client";

import Link from "next/link";
import { use, useEffect, useRef, useState } from "react";

import {
  api,
  ApiError,
  errorMessage,
  type Country,
  type Match,
  type MatchesOut,
  type Seniority,
} from "@/lib/api";

const COUNTRY_KEY = "matchlens.country";

function storedCountry(): string | undefined {
  try {
    return window.localStorage.getItem(COUNTRY_KEY) ?? undefined;
  } catch {
    return undefined; // private mode or blocked storage: fall back to the resume's country
  }
}

function storeCountry(value: string): void {
  try {
    window.localStorage.setItem(COUNTRY_KEY, value);
  } catch {
    // Not remembering the choice is fine.
  }
}
import { formatPostedAgo, sourceLabel } from "@/lib/format";

const LEVELS: { value: Seniority; label: string }[] = [
  { value: "intern", label: "Intern" },
  { value: "junior", label: "Junior" },
  { value: "mid", label: "Mid" },
  { value: "senior", label: "Senior" },
  { value: "lead", label: "Lead" },
];
const POSTED: { value: number | null; label: string }[] = [
  { value: null, label: "Any time" },
  { value: 30, label: "Past 30 days" },
  { value: 7, label: "Past week" },
];

type State =
  | { kind: "loading" }
  | { kind: "ok"; data: MatchesOut }
  | { kind: "gone" }
  | { kind: "error"; message: string };

function fit(score: number): { label: string; className: string } {
  if (score >= 80)
    return { label: "Strong fit", className: "bg-emerald-600 text-white" };
  if (score >= 60)
    return { label: "Good fit", className: "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/60 dark:text-emerald-100" };
  if (score >= 40)
    return { label: "Partial fit", className: "bg-amber-100 text-amber-900 dark:bg-amber-900/50 dark:text-amber-100" };
  return { label: "Weak fit", className: "bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300" };
}

function Chips({ label, items, tone }: { label: string; items: string[]; tone: "have" | "missing" }) {
  if (!items.length) return null;
  const color =
    tone === "have"
      ? "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-100"
      : "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100";
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="text-zinc-500">{label}</span>
      {items.map((skill) => (
        <span key={skill} className={`rounded border px-1.5 py-0.5 ${color}`}>
          {skill}
        </span>
      ))}
    </div>
  );
}

function JobCard({ match, rank, resumeId }: { match: Match; rank: number; resumeId: string }) {
  const { job } = match;
  const badge = fit(match.score);
  const posted = formatPostedAgo(job.posted_at);
  const details = [job.location, job.salary, posted && `posted ${posted}`].filter(Boolean);
  return (
    <li className="space-y-3 rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-start gap-3">
        <div
          className={`flex w-14 shrink-0 flex-col items-center rounded-lg px-1 py-1.5 ${badge.className}`}
          title={match.llm_score === null ? "Similarity and skill-overlap score" : "AI fit score"}
        >
          <span className="text-lg font-semibold leading-none">{match.score}</span>
          <span className="mt-0.5 text-[10px] leading-tight">{badge.label}</span>
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs text-zinc-500">#{rank}</p>
          <h3 className="font-medium leading-snug">
            <a href={job.url} target="_blank" rel="noopener" className="hover:underline">
              {job.title}
            </a>
          </h3>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">{job.company}</p>
          {details.length > 0 && <p className="text-xs text-zinc-500">{details.join(" · ")}</p>}
        </div>
      </div>
      <p className="text-sm">{match.reason}</p>
      <Chips label="You have" items={match.matched_skills} tone="have" />
      <Chips label="Missing" items={match.missing_skills} tone="missing" />
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm font-medium">
        <a
          href={job.url}
          target="_blank"
          rel="noopener"
          className="text-emerald-700 hover:underline dark:text-emerald-400"
        >
          View job on {sourceLabel(job.source)} ↗
        </a>
        <Link
          href={`/resume/${resumeId}/ats?job=${job.id}&title=${encodeURIComponent(`${job.title} at ${job.company}`)}`}
          className="text-zinc-700 hover:underline dark:text-zinc-300"
        >
          Check ATS fit
        </Link>
      </div>
    </li>
  );
}

export function MatchesLoader({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <MatchesView resumeId={id} />;
}

function MatchesView({ resumeId }: { resumeId: string }) {
  const [posted, setPosted] = useState<number | null>(null);
  const [levels, setLevels] = useState<Seniority[]>([]);
  // undefined: let the server use the resume's country; "ANY": no location filter.
  const [country, setCountry] = useState<string | undefined>(storedCountry);
  const [includeUnspecified, setIncludeUnspecified] = useState(true);
  const [countries, setCountries] = useState<Country[]>([]);
  const [refresh, setRefresh] = useState(0);
  const [state, setState] = useState<State>({ kind: "loading" });
  const handledRefresh = useRef(0);

  useEffect(() => {
    let cancelled = false;
    // Only the run triggered by "try again" skips the server's cache.
    const force = refresh !== handledRefresh.current;
    handledRefresh.current = refresh;
    const filters = {
      posted_within_days: posted,
      seniority: levels,
      country,
      include_unspecified: includeUnspecified,
    };
    api.getMatches(resumeId, filters, force).then(
      (data) => {
        if (!cancelled) setState({ kind: "ok", data });
      },
      (err: unknown) => {
        if (cancelled) return;
        const gone = err instanceof ApiError && (err.status === 404 || err.status === 422);
        setState(gone ? { kind: "gone" } : { kind: "error", message: errorMessage(err) });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [resumeId, posted, levels, country, includeUnspecified, refresh]);

  useEffect(() => {
    let cancelled = false;
    api.getCountries().then(
      (list) => {
        if (!cancelled) setCountries(list);
      },
      () => {}, // the selector just keeps its current value
    );
    return () => {
      cancelled = true;
    };
  }, []);

  function changePosted(value: number | null) {
    setState({ kind: "loading" });
    setPosted(value);
  }

  function toggleLevel(level: Seniority) {
    setState({ kind: "loading" });
    setLevels((current) =>
      current.includes(level) ? current.filter((l) => l !== level) : [...current, level],
    );
  }

  function changeCountry(value: string) {
    setState({ kind: "loading" });
    setCountry(value);
    storeCountry(value);
  }

  function changeIncludeUnspecified(value: boolean) {
    setState({ kind: "loading" });
    setIncludeUnspecified(value);
  }

  function retry() {
    setState({ kind: "loading" });
    setRefresh((n) => n + 1);
  }

  if (state.kind === "gone") {
    return (
      <div className="space-y-3">
        <h1 className="text-xl font-semibold">This resume is no longer available</h1>
        <p className="text-zinc-600 dark:text-zinc-400">
          Resumes are deleted 24 hours after upload, or when you delete them.
        </p>
        <Link href="/" className="font-medium text-emerald-700 hover:underline dark:text-emerald-400">
          Upload a resume
        </Link>
      </div>
    );
  }

  // What the server actually applied (it may have used the resume's country).
  const appliedCountry = state.kind === "ok" ? state.data.filters.country : undefined;
  const selectValue = country ?? appliedCountry ?? "ANY";

  const pill = (active: boolean) =>
    `rounded-full border px-3 py-1 text-sm ${
      active
        ? "border-emerald-600 bg-emerald-600 text-white"
        : "border-zinc-300 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
    }`;

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <Link href={`/resume/${resumeId}`} className="text-sm text-zinc-500 hover:underline">
          ← Your profile
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">Your matches</h1>
        {state.kind === "ok" && (
          <p className="text-sm text-zinc-500">
            Top {state.data.matches.length} of {state.data.candidates} closest remote jobs
            {state.data.reranked && state.data.model ? `, scored by ${state.data.model}` : ""}
            {state.data.cached ? " (saved results)" : ` in ${(state.data.timings.total_ms / 1000).toFixed(1)} s`}
          </p>
        )}
      </header>

      <div className="space-y-3" role="group" aria-label="Filters">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <label htmlFor="country" className="w-12 text-sm text-zinc-500">
            Where
          </label>
          <select
            id="country"
            value={selectValue}
            onChange={(event) => changeCountry(event.target.value)}
            className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          >
            <option value="ANY">Anywhere (no location filter)</option>
            {countries.map((c) => (
              <option key={c.code} value={c.code}>
                Open to someone in {c.name}
              </option>
            ))}
          </select>
          {selectValue !== "ANY" && (
            <label className="flex items-center gap-1.5 text-sm text-zinc-600 dark:text-zinc-400">
              <input
                type="checkbox"
                checked={includeUnspecified}
                onChange={(event) => changeIncludeUnspecified(event.target.checked)}
              />
              Include jobs that don&apos;t say where
            </label>
          )}
        </div>
        {selectValue === "ANY" && (
          <p className="text-xs text-amber-700 dark:text-amber-400">
            Most remote jobs are limited to certain countries. Choose yours to hide ones you
            can&apos;t take.
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-12 text-sm text-zinc-500">Posted</span>
          {POSTED.map((option) => (
            <button
              key={option.label}
              type="button"
              aria-pressed={posted === option.value}
              onClick={() => changePosted(option.value)}
              className={pill(posted === option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-12 text-sm text-zinc-500">Level</span>
          {LEVELS.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={levels.includes(option.value)}
              onClick={() => toggleLevel(option.value)}
              className={pill(levels.includes(option.value))}
            >
              {option.label}
            </button>
          ))}
        </div>
        <p className="text-xs text-zinc-500">
          Level filters keep jobs whose title doesn&apos;t state a level.
        </p>
      </div>

      {state.kind === "loading" && (
        <div aria-label="Finding matches" className="space-y-3">
          <p className="text-sm text-zinc-500">Ranking jobs for you… usually a few seconds.</p>
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-32 animate-pulse rounded-xl bg-zinc-200 dark:bg-zinc-800" />
          ))}
        </div>
      )}

      {state.kind === "error" && (
        <div role="alert" className="space-y-2 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-800 dark:bg-red-950/50 dark:text-red-200">
          <p>{state.message}</p>
          <button type="button" onClick={retry} className="font-medium underline">
            Try again
          </button>
        </div>
      )}

      {state.kind === "ok" && (
        <>
          {state.data.note && (
            <div className="space-y-1 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100">
              <p>{state.data.note}</p>
              <button type="button" onClick={retry} className="font-medium underline">
                Try the AI ranking again
              </button>
            </div>
          )}
          {state.data.matches.length === 0 ? (
            <p className="text-zinc-600 dark:text-zinc-400">
              No jobs match these filters. Try a wider date range or fewer levels.
            </p>
          ) : (
            <ol className="space-y-3">
              {state.data.matches.map((match, i) => (
                <JobCard key={match.job.id} match={match} rank={i + 1} resumeId={resumeId} />
              ))}
            </ol>
          )}
        </>
      )}
    </div>
  );
}
