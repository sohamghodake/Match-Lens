"use client";

import { useEffect, useState } from "react";

import { api, API_URL, ApiError, type DbHealth, type Health } from "@/lib/api";

type Check<T> =
  | { state: "checking" }
  | { state: "ok"; data: T }
  | { state: "down"; message: string };

function describe(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = (err.body as { detail?: unknown } | null)?.detail;
    return typeof detail === "string" ? `${err.message}: ${detail}` : err.message;
  }
  return String(err);
}

function Dot({ state }: { state: Check<unknown>["state"] }) {
  const color = {
    checking: "bg-zinc-400 animate-pulse",
    ok: "bg-emerald-500",
    down: "bg-red-500",
  }[state];
  return <span aria-hidden className={`mt-1.5 size-2.5 shrink-0 rounded-full ${color}`} />;
}

export function ApiStatus() {
  const [apiCheck, setApiCheck] = useState<Check<Health>>({ state: "checking" });
  const [dbCheck, setDbCheck] = useState<Check<DbHealth>>({ state: "checking" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api.health().then(
      (data) => {
        if (!cancelled) setApiCheck({ state: "ok", data });
      },
      (err: unknown) => {
        if (!cancelled) setApiCheck({ state: "down", message: describe(err) });
      },
    );
    api.dbHealth().then(
      (data) => {
        if (!cancelled) setDbCheck({ state: "ok", data });
      },
      (err: unknown) => {
        if (!cancelled) setDbCheck({ state: "down", message: describe(err) });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  function retry() {
    setApiCheck({ state: "checking" });
    setDbCheck({ state: "checking" });
    setAttempt((n) => n + 1);
  }

  const failed = apiCheck.state === "down" || dbCheck.state === "down";

  return (
    <section
      aria-live="polite"
      className="w-full rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900"
    >
      <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-500">System status</h2>
      <ul className="mt-4 space-y-3 text-sm">
        <li className="flex gap-3">
          <Dot state={apiCheck.state} />
          <div>
            {apiCheck.state === "checking" && <p>Checking API…</p>}
            {apiCheck.state === "ok" && (
              <>
                <p className="font-medium">API healthy</p>
                <p className="text-zinc-500">
                  v{apiCheck.data.version} · LLM {apiCheck.data.llm_model} · embeddings{" "}
                  {apiCheck.data.embed_model}
                </p>
              </>
            )}
            {apiCheck.state === "down" && (
              <>
                <p className="font-medium">API unreachable</p>
                <p className="text-zinc-500">
                  {API_URL}/health: {apiCheck.message}
                </p>
              </>
            )}
          </div>
        </li>
        <li className="flex gap-3">
          <Dot state={dbCheck.state} />
          <div>
            {dbCheck.state === "checking" && <p>Checking database…</p>}
            {dbCheck.state === "ok" && (
              <>
                <p className="font-medium">Database connected</p>
                <p className="text-zinc-500">
                  pgvector {dbCheck.data.pgvector ?? "not installed"} · migration{" "}
                  {dbCheck.data.migration ?? "none (run alembic upgrade head)"}
                </p>
              </>
            )}
            {dbCheck.state === "down" && (
              <>
                <p className="font-medium">Database unavailable</p>
                <p className="text-zinc-500">{dbCheck.message}</p>
              </>
            )}
          </div>
        </li>
      </ul>
      {failed && (
        <button
          type="button"
          onClick={retry}
          className="mt-4 rounded-md border border-zinc-300 px-3 py-1.5 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          Retry
        </button>
      )}
    </section>
  );
}
