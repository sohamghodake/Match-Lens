import type { Metadata } from "next";
import { Suspense } from "react";

import { AtsLoader } from "@/components/AtsLoader";

export const metadata: Metadata = { title: "ATS check · MatchLens" };

export default function AtsPage({ params, searchParams }: PageProps<"/resume/[id]/ats">) {
  return (
    <main className="mx-auto w-full max-w-2xl flex-1 px-4 py-10">
      <Suspense fallback={<p className="text-sm text-zinc-500">Loading…</p>}>
        <AtsLoader params={params} searchParams={searchParams} />
      </Suspense>
    </main>
  );
}
