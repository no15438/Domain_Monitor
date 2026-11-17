export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type MemoryPolicy = { importance: number; pinned: number; mode: "active" | "summary" | "archived"; reason: string; recorded_at: string };
export type Assertion = { id: string; field: string; value: JsonValue; evidence_id: string; relation: string; target_id: string | null; reason: string; valid_from: string; valid_to: string | null; recorded_at: string };
export type Citation = { id: string; source_key: string; revision: string; publisher: string; url: string; published_at: string; recorded_at: string; body_sha256: string };
export type EventResult = {
  event: { id: string; title: string; topic: string; kind: string };
  fields: Record<string, { status: "confirmed" | "conflict"; value: JsonValue; assertion_ids: string[]; evidence_ids: string[]; alternatives: Pick<Assertion, "id" | "value" | "evidence_id" | "valid_from" | "valid_to">[] }>;
  has_conflicts: boolean; memory: MemoryPolicy;
  retrieval: { weight: number; reason: string }; citations: Citation[];
};
export type QueryScope = { topic: string; q: string; valid_at: string; known_at: string; include_archived: boolean };
export type QueryResult = { scope: { topic: string; valid_at: string; known_at: string; mode: "current" | "historical" }; total: number; truncated: boolean; results: EventResult[] };
export type HistoryResult = { assertions: Assertion[]; evidence: (Citation & { body: string })[]; memory_history: MemoryPolicy[] };

const base = `${process.env.NEXT_PUBLIC_API_BASE?.trim().replace(/\/$/, "") || ""}/api/event-memory`;

export async function eventRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${base}${path}`, { ...options, cache: "no-store" });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const data = await response.json(); if (typeof data.detail === "string") detail = data.detail; } catch { /* Use status fallback. */ }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export function queryParams(scope: QueryScope) {
  const params = new URLSearchParams({ topic: scope.topic, q: scope.q, include_archived: String(scope.include_archived), limit: "100" });
  if (scope.valid_at) params.set("valid_at", scope.valid_at);
  if (scope.known_at) params.set("known_at", scope.known_at);
  return params.toString();
}

export function safeEvidenceUrl(url: string) {
  try { const parsed = new URL(url); return ["https:", "http:"].includes(parsed.protocol) ? parsed.href : undefined; }
  catch { return undefined; }
}
