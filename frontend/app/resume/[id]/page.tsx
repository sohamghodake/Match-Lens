import { Suspense } from "react";

import { ResumeLoader, ResumeSkeleton } from "@/components/ResumeLoader";

export default function ResumePage({ params }: PageProps<"/resume/[id]">) {
  // With Cache Components, unknown params are read inside <Suspense> so the
  // page shell can still be prerendered.
  return (
    <main className="mx-auto w-full max-w-2xl flex-1 px-4 py-10">
      <Suspense fallback={<ResumeSkeleton />}>
        <ResumeLoader params={params} />
      </Suspense>
    </main>
  );
}
