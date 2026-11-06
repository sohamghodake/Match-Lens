import type { Metadata } from "next";

import { LabelHome } from "@/components/label/LabelHome";

export const metadata: Metadata = { title: "Labeling · MatchLens", robots: { index: false } };

export default function LabelPage() {
  return (
    <main className="mx-auto w-full max-w-2xl flex-1 px-4 py-10">
      <LabelHome />
    </main>
  );
}
