"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";

import { ProfileView } from "@/components/ProfileView";
import { api, ApiError, errorMessage, type ResumeOut } from "@/lib/api";

type State =
  | { kind: "loading" }
  | { kind: "ok"; resume: ResumeOut }
  | { kind: "gone" }
  | { kind: "error"; message: string };

export function ResumeLoader({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    api.getResume(id).then(
      (resume) => {
        if (!cancelled) setState({ kind: "ok", resume });
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
  }, [id]);

  if (state.kind === "loading") return <ResumeSkeleton />;
  if (state.kind === "ok") return <ProfileView resume={state.resume} />;
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-semibold">
        {state.kind === "gone" ? "This resume is no longer available" : "Couldn't load this resume"}
      </h1>
      <p className="text-zinc-600 dark:text-zinc-400">
        {state.kind === "gone"
          ? "Resumes are deleted 24 hours after upload, or when you delete them."
          : state.message}
      </p>
      <Link href="/" className="font-medium text-emerald-700 hover:underline dark:text-emerald-400">
        Upload a resume
      </Link>
    </div>
  );
}

export function ResumeSkeleton() {
  return (
    <div aria-label="Loading resume" className="animate-pulse space-y-4">
      <div className="h-4 w-24 rounded bg-zinc-200 dark:bg-zinc-800" />
      <div className="h-7 w-64 rounded bg-zinc-200 dark:bg-zinc-800" />
      <div className="h-24 rounded bg-zinc-200 dark:bg-zinc-800" />
    </div>
  );
}
