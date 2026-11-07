"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AtsPanel } from "@/components/AtsPanel";
import { api, errorMessage, type ResumeOut, type Seniority } from "@/lib/api";
import { formatDateRange, formatTimeUntil, formatYears } from "@/lib/format";

const SENIORITY_LABEL: Record<Seniority, string> = {
  intern: "Intern",
  junior: "Junior",
  mid: "Mid-level",
  senior: "Senior",
  lead: "Lead / Staff",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-500">{title}</h2>
      {children}
    </section>
  );
}

export function ProfileView({ resume }: { resume: ResumeOut }) {
  const router = useRouter();
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const { profile } = resume;

  async function deleteNow() {
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteResume(resume.id);
      router.push("/");
    } catch (err) {
      setDeleteError(errorMessage(err));
      setDeleting(false);
    }
  }

  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <p className="text-sm text-zinc-500">Parsed profile</p>
        <h1 className="text-2xl font-semibold tracking-tight">
          {profile.headline ?? "Your profile"}
        </h1>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="rounded-full bg-emerald-100 px-2.5 py-0.5 font-medium text-emerald-900 dark:bg-emerald-900/50 dark:text-emerald-100">
            {SENIORITY_LABEL[profile.seniority]}
          </span>
          <span className="text-zinc-600 dark:text-zinc-400">
            {formatYears(profile.total_years_experience)}
          </span>
        </div>
        <Link
          href={`/resume/${resume.id}/matches`}
          className="inline-block rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700"
        >
          Find matching jobs →
        </Link>
      </header>

      {resume.sample && (
        <p className="rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-100">
          This is a shared sample resume for a fictional backend engineer.{" "}
          <Link href="/" className="font-medium underline">
            Upload your own
          </Link>{" "}
          to see your matches.
        </p>
      )}

      {resume.warnings.length > 0 && (
        <ul className="space-y-1 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100">
          {resume.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}

      <Section title={`Skills (${profile.skills.length})`}>
        {profile.skills.length ? (
          <ul className="flex flex-wrap gap-2">
            {profile.skills.map((skill) => (
              <li
                key={skill}
                className="rounded-md border border-zinc-200 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
              >
                {skill}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-zinc-500">No skills found.</p>
        )}
      </Section>

      {profile.roles.length > 0 && (
        <Section title="Experience">
          <ol className="space-y-4 border-l border-zinc-200 pl-4 dark:border-zinc-800">
            {profile.roles.map((role, i) => (
              <li key={`${role.title}-${role.company}-${i}`}>
                <p className="font-medium">{role.title}</p>
                <p className="text-sm text-zinc-600 dark:text-zinc-400">
                  {role.company}
                  {role.location ? ` · ${role.location}` : ""}
                </p>
                <p className="text-sm text-zinc-500">{formatDateRange(role.start, role.end)}</p>
              </li>
            ))}
          </ol>
        </Section>
      )}

      {(profile.projects?.length ?? 0) > 0 && (
        <Section title="Projects">
          <ul className="space-y-3">
            {profile.projects?.map((project, i) => (
              <li key={`${project.name}-${i}`}>
                <p className="font-medium">{project.name}</p>
                {project.summary && (
                  <p className="text-sm text-zinc-600 dark:text-zinc-400">{project.summary}</p>
                )}
                {project.skills.length > 0 && (
                  <p className="text-xs text-zinc-500">{project.skills.join(" · ")}</p>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {profile.education.length > 0 && (
        <Section title="Education">
          <ul className="space-y-3">
            {profile.education.map((school, i) => (
              <li key={`${school.institution}-${i}`}>
                <p className="font-medium">{school.institution}</p>
                <p className="text-sm text-zinc-600 dark:text-zinc-400">
                  {[school.degree, school.field].filter(Boolean).join(", ")}
                  {school.end ? ` · ${school.end}` : ""}
                </p>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="ATS check">
        <AtsPanel resumeId={resume.id} />
      </Section>

      <footer className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-zinc-200 pt-4 text-sm dark:border-zinc-800">
        {!resume.sample && (
          <>
            <span className="text-zinc-500">
              Deleted automatically {formatTimeUntil(resume.expires_at)}.
            </span>
            <button
              type="button"
              onClick={deleteNow}
              disabled={deleting}
              className="font-medium text-red-700 hover:underline disabled:opacity-60 dark:text-red-400"
            >
              {deleting ? "Deleting…" : "Delete now"}
            </button>
          </>
        )}
        <Link href="/" className="font-medium text-emerald-700 hover:underline dark:text-emerald-400">
          Upload another resume
        </Link>
        {deleteError && (
          <p role="alert" className="w-full text-red-700 dark:text-red-400">
            {deleteError}
          </p>
        )}
      </footer>
    </div>
  );
}
