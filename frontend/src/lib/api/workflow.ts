import { BASE, fetchWithRetry } from "./shared";
import type { JsonValue, Assertion, Citation } from "./eventMemory";

export interface MemoryScope {
  event_id: string;
  title: string;
  valid_at?: string;
  known_at?: string;
}

export interface WorkflowState {
  event: { id: string; title: string; topic: string; kind: string; recorded_at?: string };
  fields: Record<string, { status: string; value: JsonValue; assertion_ids: string[]; evidence_ids: string[]; alternatives?: Assertion[] }>;
  has_conflicts: boolean;
  valid_at: string;
  known_at: string;
}

export interface MemoryUpdate {
  id: string;
  event_id: string;
  title: string;
  kind: string;
  field: string;
  previous_value: JsonValue;
  value: JsonValue;
  valid_from: string;
  recorded_at: string;
  review_status: string;
  source_count: number;
}

export interface WorkflowEvidence extends Citation {
  body: string;
  content_status?: string;
  passages: { quote: string; start: number; end: number; field: string; assertion_id: string }[];
}

export interface WorkflowDetail {
  state: WorkflowState;
  history: { assertions: Assertion[]; evidence?: WorkflowEvidence[] };
  evidence: WorkflowEvidence[];
  model_version: number;
  expected_version?: string | null;
}

export interface WorkflowCandidate {
  id: string;
  topic_id: number;
  revision_id: string;
  event_id: string | null;
  title: string;
  developer: string;
  model: string;
  version: string;
  status: string;
  valid_from: string | null;
  quote: string;
  relation: string;
  target_id: string | null;
  review_status: string;
  issues: string[];
  expected_version: string;
  created_at: string;
  source?: { url: string; publisher: string; body: string; published_at: string; revision: string };
}

export interface UpdatesResponse {
  updates: MemoryUpdate[];
  events: WorkflowState[];
  pending_count: number;
  coverage: { model: string; version: number; authority: string; migrated_kinds?: string[] };
}

export type CandidateReview = {
  action: "accept" | "reject" | "defer";
  reason: string;
  expected_version: string;
  developer?: string;
  model?: string;
  version?: string;
  status?: string;
  valid_from?: string | null;
  quote?: string;
  event_id?: string | null;
  relation?: string;
  target_id?: string | null;
};

async function request<T>(topicId: number, path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetchWithRetry(`${BASE}/api/topics/${topicId}/memory${path}`, { ...options, cache: "no-store" });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { const data = await response.json(); if (typeof data.detail === "string") message = data.detail; } catch { /* Use status fallback. */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export function workflowParams(q = "", validAt = "", knownAt = "") {
  const params = new URLSearchParams({ q, limit: "50" });
  if (validAt) params.set("valid_at", validAt);
  if (knownAt) params.set("known_at", knownAt);
  return params.toString();
}

export const fetchMemoryUpdates = (topicId: number, q = "", validAt = "", knownAt = "", signal?: AbortSignal) =>
  request<UpdatesResponse>(topicId, `/updates?${workflowParams(q, validAt, knownAt)}`, { signal });

export const fetchMemoryDetail = (topicId: number, eventId: string, validAt = "", knownAt = "", signal?: AbortSignal) =>
  request<WorkflowDetail>(topicId, `/events/${encodeURIComponent(eventId)}?${workflowParams("", validAt, knownAt)}`, { signal });

export const fetchMemoryCandidates = (topicId: number, signal?: AbortSignal) =>
  request<{ candidates: WorkflowCandidate[] }>(topicId, "/candidates", { signal });

export const reviewMemoryCandidate = (topicId: number, candidateId: string, review: CandidateReview) =>
  request<{ status?: string }>(topicId, `/candidates/${encodeURIComponent(candidateId)}/review`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(review),
  });

export function memoryValue(value: JsonValue | undefined): string {
  if (value === null || value === undefined) return "Unknown";
  return typeof value === "string" ? value : JSON.stringify(value);
}
