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

export type ResumeProfile = {
  headline: string | null;
  seniority: Seniority;
  total_years_experience: number;
  skills: string[];
  roles: Role[];
  education: Education[];
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

type RequestOptions = { method?: string; body?: BodyInit; timeoutMs?: number };

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, timeoutMs = 10_000 } = options;
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method,
      body,
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
    // Parsing calls an LLM; allow for a slow model (and, in production, a cold start).
    return request<ResumeOut>("/resumes", { method: "POST", body: form, timeoutMs: 120_000 });
  },
  getResume: (id: string) => request<ResumeOut>(`/resumes/${encodeURIComponent(id)}`),
  deleteResume: (id: string) =>
    request<void>(`/resumes/${encodeURIComponent(id)}`, { method: "DELETE" }),
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
