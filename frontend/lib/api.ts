// Typed client for the MatchLens FastAPI backend. The browser talks to the API
// directly, so NEXT_PUBLIC_API_URL is inlined at build time (set it on Vercel).
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8100").replace(
  /\/+$/,
  "",
);

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

export class ApiError extends Error {
  readonly status: number; // 0 when the request never got a response
  readonly body: unknown;

  constructor(status: number, body: unknown, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function request<T>(path: string, timeoutMs = 10_000): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { signal: AbortSignal.timeout(timeoutMs) });
  } catch (err) {
    const timedOut = err instanceof DOMException && err.name === "TimeoutError";
    throw new ApiError(0, null, timedOut ? "timed out" : "network error");
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(response.status, body, `HTTP ${response.status}`);
  }
  return body as T;
}

export const api = {
  health: () => request<Health>("/health"),
  dbHealth: () => request<DbHealth>("/health/db"),
};
