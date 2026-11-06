"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { errorMessage } from "@/lib/api";
import { evalApi, toolsDisabled, type EvalDocument } from "@/lib/evalApi";

const TARGET = 30;

const STATUS: Record<EvalDocument["status"], { label: string; className: string }> = {
  none: { label: "Not labeled", className: "bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300" },
  draft: { label: "Draft", className: "bg-amber-100 text-amber-900 dark:bg-amber-900/50 dark:text-amber-100" },
  verified: { label: "Verified", className: "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/50 dark:text-emerald-100" },
};

export function LabelHome() {
  const [docs, setDocs] = useState<EvalDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    evalApi.documents().then(
      (list) => {
        if (!cancelled) setDocs(list);
      },
      (err: unknown) => {
        if (cancelled) return;
        setError(
          toolsDisabled(err)
            ? "The labeling tools are off. Start the backend with EVAL_TOOLS=true (docker compose does)."
            : errorMessage(err),
        );
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const verified = docs?.filter((d) => d.status === "verified").length ?? 0;

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Labeling</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Local tools for Phase 6. Labels stay in <code>backend/eval/private/</code>, which git
          ignores.
        </p>
      </header>

      <section className="space-y-2 rounded-xl border border-zinc-200 bg-white p-4 text-sm dark:border-zinc-800 dark:bg-zinc-900">
        <h2 className="font-medium">1 · Resume labels ({verified} of {TARGET} verified)</h2>
        <div className="h-2 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800" aria-hidden>
          <div className="h-full bg-emerald-600" style={{ width: `${Math.min(100, (100 * verified) / TARGET)}%` }} />
        </div>
        <p className="text-zinc-600 dark:text-zinc-400">
          Put PDF or DOCX resumes in <code>backend/eval/private/resumes/</code> (yours, friends&apos;
          with permission, public samples), then label each one below.
        </p>
      </section>

      <section className="space-y-2 rounded-xl border border-zinc-200 bg-white p-4 text-sm dark:border-zinc-800 dark:bg-zinc-900">
        <h2 className="font-medium">2 · Job relevance</h2>
        <p className="text-zinc-600 dark:text-zinc-400">
          Build the pool with <code>docker compose exec backend python -m eval.build_pool</code>,
          then judge it.
        </p>
        <Link href="/label/relevance" className="font-medium text-emerald-700 hover:underline dark:text-emerald-400">
          Judge job relevance →
        </Link>
      </section>

      {error && (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950/50 dark:text-red-200">
          {error}
        </p>
      )}
      {docs && (
        <ul className="divide-y divide-zinc-200 rounded-xl border border-zinc-200 bg-white dark:divide-zinc-800 dark:border-zinc-800 dark:bg-zinc-900">
          {docs.map((doc) => (
            <li key={doc.id}>
              <Link
                href={`/label/doc?id=${encodeURIComponent(doc.id)}`}
                className="flex items-center justify-between gap-3 px-4 py-3 text-sm hover:bg-zinc-50 dark:hover:bg-zinc-800/60"
              >
                <span className="min-w-0 truncate">
                  <span className="text-zinc-500">{doc.origin === "sample" ? "sample · " : ""}</span>
                  {doc.file}
                </span>
                <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${STATUS[doc.status].className}`}>
                  {STATUS[doc.status].label}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
