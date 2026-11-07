"use client";

import { useEffect, useState } from "react";

import { api, errorMessage, type PipelineStatus } from "@/lib/api";
import { formatRunTime, sourceLabel } from "@/lib/format";

const when = (iso: string) => formatRunTime(iso);

export function PipelineStatusCard() {
  const [data, setData] = useState<PipelineStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.pipeline().then(
      (status) => {
        if (!cancelled) setData(status);
      },
      (err: unknown) => {
        if (!cancelled) setError(errorMessage(err));
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const last = data?.recent_runs[0];
  return (
    <section className="w-full space-y-4 rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-500">Job pipeline</h2>
      {error && <p className="text-sm text-red-700 dark:text-red-400">{error}</p>}
      {!data && !error && <p className="text-sm text-zinc-500">Loading…</p>}
      {data && (
        <>
          <dl className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <dt className="text-zinc-500">Active remote tech jobs</dt>
              <dd className="text-2xl font-semibold tabular-nums">{data.active_jobs.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-zinc-500">Added in the last 24 hours</dt>
              <dd className="text-2xl font-semibold tabular-nums">{data.added_last_24h.toLocaleString()}</dd>
            </div>
          </dl>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {data.by_source.map((s) => `${sourceLabel(s.source)} ${s.active_jobs.toLocaleString()}`).join(" · ")}
          </p>
          {last ? (
            <p className="text-sm">
              Last import {when(last.finished_at ?? last.started_at)}:{" "}
              <span className={last.status === "success" ? "text-emerald-700 dark:text-emerald-400" : "text-amber-700 dark:text-amber-400"}>
                {last.status}
              </span>
              , {last.fetched.toLocaleString()} fetched, {last.inserted} new, {last.updated} updated
              {last.errors ? `, ${last.errors} source errors` : ""}.
            </p>
          ) : (
            <p className="text-sm text-zinc-500">No import has run yet.</p>
          )}
          {data.recent_runs.length > 1 && (
            <table className="w-full text-left text-xs text-zinc-600 dark:text-zinc-400">
              <thead>
                <tr className="text-zinc-500">
                  <th className="font-normal">Run</th>
                  <th className="font-normal">Status</th>
                  <th className="text-right font-normal">Fetched</th>
                  <th className="text-right font-normal">New</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {data.recent_runs.map((run) => (
                  <tr key={run.id}>
                    <td>{when(run.started_at)}</td>
                    <td>{run.status}</td>
                    <td className="text-right">{run.fetched.toLocaleString()}</td>
                    <td className="text-right">{run.inserted}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}
