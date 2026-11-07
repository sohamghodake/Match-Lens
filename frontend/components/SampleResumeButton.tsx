"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { api, errorMessage } from "@/lib/api";

export function SampleResumeButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function trySample() {
    setBusy(true);
    setError(null);
    try {
      const resume = await api.sampleResume();
      router.push(`/resume/${resume.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <button
          type="button"
          onClick={trySample}
          disabled={busy}
          className="rounded-lg border border-zinc-300 bg-white px-4 py-2 font-medium hover:bg-zinc-100 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:bg-zinc-800"
        >
          {busy ? "Loading the sample…" : "No resume handy? Try a sample"}
        </button>
        <a href="/sample-resume.pdf" target="_blank" className="text-zinc-500 hover:underline">
          View the sample (a fictional backend engineer)
        </a>
      </div>
      {error && (
        <p role="alert" className="text-red-700 dark:text-red-400">
          {error}
        </p>
      )}
    </div>
  );
}
