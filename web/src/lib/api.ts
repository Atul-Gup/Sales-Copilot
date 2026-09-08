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

// Mirrors api/routers/chat.py::ChatCitation.
export type ChatCitation = {
  marker: number;
  section: string | null;
  text: string;
};

// Mirrors api/routers/chat.py::ChatResponse — one shape for every intent
// class (SPEC/COMPARISON/OBJECTION), per T7.1's single generation path.
export type ChatResponse = {
  text: string;
  refused: boolean;
  conceded: boolean;
  intent: "SPEC" | "COMPARISON" | "OBJECTION" | null;
  citations: ChatCitation[];
};

export function postChat(query: string): Promise<ChatResponse> {
  return request<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify({ query }),
  });
}
