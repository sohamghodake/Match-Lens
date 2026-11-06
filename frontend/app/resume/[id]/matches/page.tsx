import type { Metadata } from "next";
import { Suspense } from "react";

import { MatchesLoader } from "@/components/MatchesView";

export const metadata: Metadata = { title: "Matches · MatchLens" };

export default function MatchesPage({ params }: PageProps<"/resume/[id]/matches">) {
  return (
    <main className="mx-auto w-full max-w-2xl flex-1 px-4 py-10">
      <Suspense fallback={<p className="text-sm text-zinc-500">Loading…</p>}>
        <MatchesLoader params={params} />
      </Suspense>
    </main>
  );
}
