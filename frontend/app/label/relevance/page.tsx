import type { Metadata } from "next";

import { RelevanceLabeler } from "@/components/label/RelevanceLabeler";

export const metadata: Metadata = { title: "Judge relevance · MatchLens", robots: { index: false } };

export default function RelevancePage() {
  return (
    <main className="mx-auto w-full max-w-2xl flex-1 px-4 py-10">
      <RelevanceLabeler />
    </main>
  );
}
