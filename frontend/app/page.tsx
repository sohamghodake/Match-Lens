import { ApiStatus } from "@/components/ApiStatus";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col justify-center gap-8 px-4 py-16">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">MatchLens</h1>
        <p className="text-zinc-600 dark:text-zinc-400">
          Upload a resume and get ranked remote jobs, each with a fit score, the reason it
          matched, the skills you&apos;re missing, and an ATS score against any job description.
        </p>
      </header>
      <ApiStatus />
    </main>
  );
}
