import type { Metadata } from "next";
import { Suspense } from "react";

import { ResumeLabeler } from "@/components/label/ResumeLabeler";

export const metadata: Metadata = { title: "Label resume · MatchLens", robots: { index: false } };

export default function LabelDocPage({ searchParams }: PageProps<"/label/doc">) {
  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">
      <Suspense fallback={<p className="text-sm text-zinc-500">Loading…</p>}>
        <ResumeLabeler searchParams={searchParams} />
      </Suspense>
    </main>
  );
}
