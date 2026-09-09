// Thin fetch wrapper over the FastAPI backend (api/main.py). One base URL,
// read from NEXT_PUBLIC_API_BASE_URL — never hardcoded per call site, so
// pointing the app at a different environment is a single env var change.
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new ApiError(response.status, detail || response.statusText);
  }
  return response.json() as Promise<T>;
}

export type HealthStatus = { status: string };

export function getHealth(): Promise<HealthStatus> {
  return request<HealthStatus>("/health");
}

// Mirrors api/routers/chat.py::Claim (T7.7). One entry per `[n]` marker
// actually cited in `response`, in the order those markers appear — built
// server-side from api/services/verify.py::extract_claims, the same
// per-sentence parsing verify_grounding already does. No `marker` number is
// exposed here on purpose (it's an internal chunk-offer-order detail); the
// frontend correlates a claim to its `[n]` occurrence in `response` by
// position, not by number — see `renderResponseWithCitations` below.
export type Claim = {
  text_span: string;
  chunk_id: number;
  source: string;
};

// Mirrors api/routers/chat.py::Warning (T7.7). `type` is one of
// "must_concede" | "no_answer_outside_corpus" | "disparagement" today —
// kept as `string` here rather than a union so an unrecognized future type
// still renders (as a generic callout) instead of a TypeScript narrowing
// error.
export type Warning = {
  type: string;
  text: string;
};

// Mirrors api/routers/chat.py::ChatResponse (T7.7) — replaced the old flat
// `{text, refused, conceded, intent, citations}` shape. `refused`/`conceded`
// are gone: the frontend now derives refusal/concession styling from
// `warnings` (a `no_answer_outside_corpus` or `must_concede` entry) instead
// of separate booleans — see AssistantBubble in app/page.tsx.
export type ChatResponse = {
  response: string;
  claims: Claim[];
  warnings: Warning[];
};

export function postChat(query: string): Promise<ChatResponse> {
  return request<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify({ query }),
  });
}
