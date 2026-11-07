"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";

type State = "checking" | "awake" | "waking" | "down";

/** Free hosting sleeps after 15 idle minutes; say so instead of looking broken. */
export function ServerWake() {
  const [state, setState] = useState<State>("checking");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const slow = setTimeout(() => {
      if (!cancelled) setState((s) => (s === "checking" ? "waking" : s));
    }, 2500);
    api.health().then(
      () => {
        if (!cancelled) setState("awake");
      },
      () => {
        if (!cancelled) setState("down");
      },
    );
    return () => {
      cancelled = true;
      clearTimeout(slow);
    };
  }, [attempt]);

  if (state === "waking") {
    return (
      <p role="status" className="flex items-center gap-2 rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-100">
        <span aria-hidden className="size-4 shrink-0 animate-spin rounded-full border-2 border-sky-300 border-t-sky-700" />
        Waking up the server. It runs on free hosting that sleeps when idle, so the first
        request takes about a minute.
      </p>
    );
  }
  if (state === "down") {
    return (
      <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-800 dark:bg-red-950/50 dark:text-red-200">
        Can&apos;t reach the server right now.{" "}
        <button
          type="button"
          className="font-medium underline"
          onClick={() => {
            setState("checking");
            setAttempt((n) => n + 1);
          }}
        >
          Try again
        </button>
      </p>
    );
  }
  return null;
}
