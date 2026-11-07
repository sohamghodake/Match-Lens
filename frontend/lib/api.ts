// Typed client for the MatchLens FastAPI backend. The browser talks to the API
// directly, so NEXT_PUBLIC_API_URL is inlined at build time (set it on Vercel).
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8100").replace(
  /\/+$/,
  "",
);

export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

export type Health = {
  status: "ok";
  version: string;
  llm_model: string;
  embed_model: string;
};

export type DbHealth = {
  status: "ok" | "error";
  pgvector: string | null;
  migration: string | null;
  detail: string | null;
};

export type Seniority = "intern" | "junior" | "mid" | "senior" | "lead";

export type Role = {
  title: string;
  company: string;
  location: string | null;
  start: string | null; // "YYYY-MM" | "YYYY"
  end: string | null; // "YYYY-MM" | "YYYY" | "present"
};

export type Education = {
  institution: string;
  degree: string | null;
  field: string | null;
  end: string | null;
};

export type Project = {
  name: string;
  summary: string | null;
  skills: string[];
};

export type ResumeProfile = {
  headline: string | null;
  seniority: Seniority;
  total_years_experience: number;
  skills: string[];
  roles: Role[];
  education: Education[];
  projects?: Project[]; // absent on resumes parsed before projects were added
};

export type ResumeOut = {
  id: string;
  created_at: string;
  expires_at: string;
  profile: ResumeProfile;
  parse_method: "llm" | "fallback";
  warnings: string[];
  file: {
    kind: "pdf" | "docx";
    pages: number | null;
    columns: number;
    tables: number;
    chars: number;
    has_email: boolean;
    has_phone: boolean;
    has_linkedin: boolean;
  };
  sample: boolean; // the shared demo resume
};

export type PipelineStatus = {
  active_jobs: number;
  added_last_24h: number;
  by_source: { source: string; active_jobs: number }[];
  recent_runs: {
    id: number;
    started_at: string;
    finished_at: string | null;
    status: string;
    fetched: number;
    inserted: number;
    updated: number;
    skipped: number;
    errors: number;
  }[];
};

export type JobSource = "remotive" | "remoteok" | "greenhouse";

export type Match = {
  job: {
    id: number;
    title: string;
    company: string;
    location: string | null;
    url: string;
    source: JobSource | string;
    salary: string | null;
    seniority: Seniority | null;
    posted_at: string | null;
    regions: string[];
  };
  score: number;
  reason: string;
  matched_skills: string[];
  missing_skills: string[];
  similarity: number;
  hybrid: number;
  llm_score: number | null;
};

export type MatchFilters = {
  posted_within_days: number | null;
  seniority: Seniority[] | null;
  country: string | null; // ISO code; null = anywhere
  include_unspecified: boolean;
};

export type Country = { code: string; name: string };

export type MatchesOut = {
  resume_id: string;
  generated_at: string;
  cached: boolean;
  reranked: boolean;
  model: string | null;
  note: string | null;
  candidates: number;
  filters: MatchFilters;
  timings: { retrieve_ms: number; score_ms: number; rerank_ms: number; total_ms: number };
  tokens: number | null;
  matches: Match[];
};

export type AtsDeduction = { points: number; reason: string; suggestion: string };

export type AtsPart = {
  key: "keywords" | "sections" | "formatting" | "seniority";
  name: string;
  max_points: number;
  points: number;
  deductions: AtsDeduction[];
  notes: { message: string }[];
};

export type AtsKeyword = {
  keyword: string;
  importance: "required" | "preferred";
  status: "found" | "synonym" | "missing";
  resume_term: string | null;
};

export type AtsReport = {
  resume_id: string;
  generated_at: string;
  score: number;
  parts: AtsPart[];
  keywords: AtsKeyword[];
  job: { title: string | null; seniority: Seniority | null; min_years: number | null };
  analysis_method: "llm" | "rules";
};

export class ApiError extends Error {
  readonly status: number; // 0 when the request never got a response
  readonly body: unknown;

  constructor(status: number, body: unknown, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }

  /** The API's own explanation (FastAPI's `detail`), when it sent a readable one. */
  get detail(): string | null {
    const detail = (this.body as { detail?: unknown } | null)?.detail;
    return typeof detail === "string" ? detail : null;
  }
}

type RequestOptions = {
  method?: string;
  body?: BodyInit;
  json?: unknown;
  timeoutMs?: number;
};

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  // Long enough for a free-tier server to wake from sleep (about a minute).
  const { method = "GET", json, timeoutMs = 75_000 } = options;
  const body = json === undefined ? options.body : JSON.stringify(json);
  const headers = json === undefined ? undefined : { "Content-Type": "application/json" };
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method,
      body,
      headers,
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (err) {
    const timedOut = err instanceof DOMException && err.name === "TimeoutError";
    throw new ApiError(0, null, timedOut ? "timed out" : "network error");
  }
  if (response.status === 204) return undefined as T;
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(response.status, data, `HTTP ${response.status}`);
  }
  return data as T;
}

export const api = {
  health: () => request<Health>("/health"),
  dbHealth: () => request<DbHealth>("/health/db"),
  uploadResume: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    // Parsing calls an LLM: a free local model on CPU can take a couple of minutes,
    // and in production the server may also be waking up. Matches LLM_TIMEOUT_SECONDS.
    return request<ResumeOut>("/resumes", { method: "POST", body: form, timeoutMs: 300_000 });
  },
  getCountries: () => request<Country[]>("/locations/countries"),
  sampleResume: () => request<ResumeOut>("/resumes/sample", { method: "POST", timeoutMs: 120_000 }),
  pipeline: () => request<PipelineStatus>("/status/pipeline"),
  /** Exactly one of jobDescription / jobId. */
  ats: (resumeId: string, source: { jobDescription: string } | { jobId: number }) =>
    request<AtsReport>("/ats", {
      method: "POST",
      json: {
        resume_id: resumeId,
        ...("jobId" in source
          ? { job_id: source.jobId }
          : { job_description: source.jobDescription }),
      },
      timeoutMs: 60_000,
    }),
  getResume: (id: string) => request<ResumeOut>(`/resumes/${encodeURIComponent(id)}`),
  deleteResume: (id: string) =>
    request<void>(`/resumes/${encodeURIComponent(id)}`, { method: "DELETE" }),
  /** `country`: an ISO code, "ANY" for no filter, or undefined for the resume's country. */
  getMatches: (
    id: string,
    filters: Partial<Omit<MatchFilters, "country">> & { country?: string } = {},
    refresh = false,
  ) => {
    const params = new URLSearchParams();
    if (filters.posted_within_days) params.set("posted_within_days", String(filters.posted_within_days));
    for (const level of filters.seniority ?? []) params.append("seniority", level);
    if (filters.country) params.set("country", filters.country);
    if (filters.include_unspecified === false) params.set("include_unspecified", "false");
    if (refresh) params.set("refresh", "true");
    const query = params.size ? `?${params}` : "";
    // An LLM call, possibly waiting out a free-tier rate limit.
    return request<MatchesOut>(`/resumes/${encodeURIComponent(id)}/matches${query}`, {
      timeoutMs: 120_000,
    });
  },
};

/** A sentence for the user, from any error thrown by `api`. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.detail) return err.detail;
    if (err.status === 0) {
      return err.message === "timed out"
        ? "The server took too long to answer. Please try again."
        : "Couldn't reach the server. Check your connection and try again.";
    }
    return `Something went wrong (${err.message}). Please try again.`;
  }
  return "Something went wrong. Please try again.";
}
