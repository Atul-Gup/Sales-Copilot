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

// Mirrors api/services/spec_query.py::VariantLabel.
export type VariantLabel = {
  id: number;
  brand: string;
  model: string;
  variant_name: string;
};

export function getVariants(): Promise<VariantLabel[]> {
  return request<VariantLabel[]>("/variants");
}

// Mirrors api/services/spec_query.py::SourceRef — every cited fact carries
// one of these, and the comparison view (T7.2) renders it inline on every
// row rather than behind a tooltip.
export type SourceRef = {
  id: number;
  kind: string;
  publisher: string;
  url: string;
  document_title: string | null;
  retrieved_at: string;
  verified_at: string | null;
};

// Mirrors api/services/compare.py::DiffValue / SpecDiffRow.
export type DiffValue = {
  value_text: string | null;
  value_num: string | null;
  source: SourceRef;
};

export type SpecDiffRow = {
  attribute: string;
  unit: string | null;
  variant_a: DiffValue | null;
  variant_b: DiffValue | null;
};

export function getComparison(
  variantAId: number,
  variantBId: number,
): Promise<SpecDiffRow[]> {
  const params = new URLSearchParams({
    variant_a_id: String(variantAId),
    variant_b_id: String(variantBId),
  });
  return request<SpecDiffRow[]>(`/compare?${params}`);
}

// Mirrors api/services/compare.py::IncludedItem / UnmatchableItem / EquippedPriceComparison.
export type IncludedItem = {
  feature_key: string;
  cost_paise: number;
  source: SourceRef;
};

export type UnmatchableItem = {
  feature_key: string;
  reason: "not_offered" | "cost_not_sourced";
};

export type EquippedPriceComparison = {
  base_variant_id: number;
  competitor_variant_id: number;
  base_price_paise: number | null;
  competitor_base_price_paise: number | null;
  added_cost_paise: number;
  competitor_equipped_price_paise: number | null;
  included_items: IncludedItem[];
  unmatchable_items: UnmatchableItem[];
};

export function getEquippedPrice(
  baseVariantId: number,
  competitorVariantId: number,
): Promise<EquippedPriceComparison> {
  const params = new URLSearchParams({
    base_variant_id: String(baseVariantId),
    competitor_variant_id: String(competitorVariantId),
  });
  return request<EquippedPriceComparison>(`/compare/equipped-price?${params}`);
}

// Mirrors api/objection/state.py::GeneratedResponse.
export type ObjectionResponse = {
  what_is_true: string;
  how_to_frame_it: string;
  what_not_to_claim: string;
  raw_text: string;
};

// Mirrors api/objection/stream.py::StreamEvent, as forwarded by
// api/routers/objection.py's SSE framing.
export type ObjectionStreamEvent =
  | { type: "category"; category: string; confidence: number }
  | { type: "token"; text: string }
  | { type: "abstained"; response: ObjectionResponse }
  | { type: "refused"; violations: string[]; response: ObjectionResponse }
  | { type: "done"; violations: string[]; response: ObjectionResponse };

function parseSseFrame(frame: string): ObjectionStreamEvent | null {
  let eventType = "";
  let data = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event: ")) eventType = line.slice("event: ".length);
    else if (line.startsWith("data: ")) data = line.slice("data: ".length);
  }
  if (!eventType || !data) return null;
  return { type: eventType, ...JSON.parse(data) } as ObjectionStreamEvent;
}

// `EventSource` can't send a POST body, so the SSE stream is read by hand
// off `fetch`'s `ReadableStream` instead — frames are separated by a blank
// line (`\n\n`) per api/routers/objection.py's `_format_sse`.
export async function* streamObjection(
  objectionText: string,
  context: Record<string, unknown> = {},
): AsyncGenerator<ObjectionStreamEvent> {
  const response = await fetch(`${API_BASE_URL}/objection/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ objection_text: objectionText, context }),
  });
  if (!response.ok || !response.body) {
    const detail = await response.text().catch(() => response.statusText);
    throw new ApiError(response.status, detail || response.statusText);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let separatorIndex: number;
    while ((separatorIndex = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, separatorIndex);
      buffer = buffer.slice(separatorIndex + 2);
      const event = parseSseFrame(frame);
      if (event) yield event;
    }
  }
}
