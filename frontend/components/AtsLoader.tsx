"use client";

import Link from "next/link";
import { use } from "react";

import { AtsPanel } from "@/components/AtsPanel";

export function AtsLoader({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = use(params);
  const query = use(searchParams);
  const job = Number(Array.isArray(query.job) ? query.job[0] : query.job);
  const jobId = Number.isInteger(job) && job > 0 ? job : undefined;
  const title = typeof query.title === "string" ? query.title : null;

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <Link
          href={jobId ? `/resume/${id}/matches` : `/resume/${id}`}
          className="text-sm text-zinc-500 hover:underline"
        >
          ← {jobId ? "Your matches" : "Your profile"}
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">ATS check</h1>
        {title && <p className="text-zinc-600 dark:text-zinc-400">{title}</p>}
      </header>
      <AtsPanel resumeId={id} jobId={jobId} />
    </div>
  );
}
