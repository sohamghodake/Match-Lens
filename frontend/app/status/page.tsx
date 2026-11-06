import type { Metadata } from "next";

import { ApiStatus } from "@/components/ApiStatus";

export const metadata: Metadata = { title: "Status · MatchLens" };

export default function StatusPage() {
  return (
    <main className="mx-auto w-full max-w-2xl flex-1 space-y-6 px-4 py-16">
      <h1 className="text-2xl font-semibold tracking-tight">Status</h1>
      <ApiStatus />
    </main>
  );
}
