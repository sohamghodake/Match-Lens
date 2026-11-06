// Local-only labeling tools (backend EVAL_TOOLS=true). Not used by the public app.
import { API_URL, ApiError, type Seniority } from "@/lib/api";

export type DocStatus = "none" | "draft" | "verified";

export type EvalDocument = {
  id: string; // "sample:<file>" or "private:<file>"
  origin: "sample" | "private";
  file: string;
  status: DocStatus;
};

export type LabelRole = { title: string; company: string; start: string | null; end: string | null };
export type LabelEducation = {
  institution: string;
  degree: string | null;
  field: string | null;
  year: string | null;
};

export type ParserLabel = {
  file: string;
  seniority: Seniority | null;
  roles: LabelRole[];
  education: LabelEducation[];
  skills: string[];
  notes: string;
  verified: boolean;
};

export type DocumentDetail = { document: EvalDocument; text: string; label: ParserLabel | null };

export type PoolJob = {
  title: string;
  company: string;
  location: string | null;
  url: string;
  source: string;
  seniority: string | null;
  skills: string[];
  excerpt: string;
};

export type Pool = {
  created_at: string;
  k: number;
  systems: string[];
  resumes: { key: string; profile: string; runs: Record<string, number[]>; jobs: number[] }[];
  jobs: Record<string, PoolJob>;
};

export type Grade = 0 | 1 | 2;

async function call<T>(path: string, init: RequestInit = {}, timeoutMs = 15_000): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/eval${path}`, {
      ...init,
      headers: init.body ? { "Content-Type": "application/json" } : undefined,
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch {
    throw new ApiError(0, null, "network error");
  }
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, data, `HTTP ${response.status}`);
  return data as T;
}

export const evalApi = {
  documents: () => call<EvalDocument[]>("/documents"),
  document: (id: string) => call<DocumentDetail>(`/documents/${encodeURIComponent(id)}`),
  draft: (id: string) =>
    call<ParserLabel>(`/documents/${encodeURIComponent(id)}/draft`, { method: "POST" }, 120_000),
  save: (id: string, label: ParserLabel) =>
    call<ParserLabel>(`/documents/${encodeURIComponent(id)}/label`, {
      method: "PUT",
      body: JSON.stringify(label),
    }),
  relevance: () => call<{ pool: Pool | null; judgments: Record<string, Record<string, Grade>> }>("/relevance"),
  judge: (resumeKey: string, jobId: number, grade: Grade | null) =>
    call<Record<string, Grade>>(
      `/relevance/${encodeURIComponent(resumeKey)}/${jobId}`,
      { method: "PUT", body: JSON.stringify({ grade }) },
    ),
};

/** A 404 from /eval means the backend wasn't started with EVAL_TOOLS=true. */
export function toolsDisabled(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
}
