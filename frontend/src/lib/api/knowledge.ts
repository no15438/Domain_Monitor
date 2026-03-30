import { BASE, fetchWithRetry, safeJson } from "./shared";
import type {
  CachedSummary,
  Claim,
  EventClaimSummary,
  EventRecord,
  EvidenceSet,
  InsightSummary,
  Snapshot,
  SnapshotDelta,
  SynthesisArtifact,
  TemporalSnapshot,
  TopicInsight,
} from "./types";

export async function fetchSnapshots(topicId: number): Promise<Snapshot[]> {
  const res = await fetch(`${BASE}/api/topics/${topicId}/snapshots`);
  return safeJson(res, []);
}

export async function fetchTemporalSnapshots(
  topicId: number,
  window = "daily",
): Promise<TemporalSnapshot[]> {
  const res = await fetch(`${BASE}/api/topics/${topicId}/snapshots?window=${window}`);
  return safeJson(res, []);
}

export async function updateSnapshot(
  id: number,
  content: string,
): Promise<boolean> {
  const res = await fetch(`${BASE}/api/snapshots/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  return res.ok;
}

export async function deleteSnapshot(
  id: number,
  topicId: number,
): Promise<boolean> {
  const res = await fetch(`${BASE}/api/snapshots/${id}?topic_id=${topicId}`, {
    method: "DELETE",
  });
  return res.ok;
}

export async function fetchClaims(
  topicId: number,
  status?: string,
): Promise<Claim[]> {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const res = await fetch(`${BASE}/api/topics/${topicId}/claims${suffix}`);
  return safeJson(res, { claims: [] }).then(
    (data) => (data as { claims: Claim[] }).claims ?? [],
  );
}

export async function fetchEvidence(topicId: number): Promise<EvidenceSet[]> {
  const res = await fetch(`${BASE}/api/topics/${topicId}/evidence`);
  return safeJson(res, { evidence: [] }).then(
    (data) => (data as { evidence: EvidenceSet[] }).evidence ?? [],
  );
}

export async function fetchActiveEvents(
  topicId: number,
): Promise<EventRecord[]> {
  const res = await fetch(`${BASE}/api/topics/${topicId}/events/active`);
  return safeJson(res, { events: [] }).then(
    (data) => (data as { events: EventRecord[] }).events ?? [],
  );
}

export async function fetchEventHistory(
  topicId: number,
): Promise<EventRecord[]> {
  const res = await fetch(`${BASE}/api/topics/${topicId}/events/history`);
  return safeJson(res, { events: [] }).then(
    (data) => (data as { events: EventRecord[] }).events ?? [],
  );
}

export async function fetchSnapshotDeltas(
  topicId: number,
): Promise<SnapshotDelta[]> {
  const res = await fetch(`${BASE}/api/topics/${topicId}/snapshot-deltas`);
  return safeJson(res, { deltas: [] }).then(
    (data) => (data as { deltas: SnapshotDelta[] }).deltas ?? [],
  );
}

export async function fetchSynthesisArtifact(
  topicId: number,
  artifactType: "global-overview" | "evolution-report",
): Promise<SynthesisArtifact | null> {
  const path =
    artifactType === "global-overview"
      ? `${BASE}/api/topics/${topicId}/synthesis/global-overview`
      : `${BASE}/api/topics/${topicId}/synthesis/evolution-report`;
  const res = await fetch(path, { cache: "no-store" });
  const data = await safeJson(res, { artifact: null });
  return (data as { artifact: SynthesisArtifact | null }).artifact ?? null;
}

export async function fetchGlobalOverview(
  topicId: number,
): Promise<{ content: string | null }> {
  const artifact = await fetchSynthesisArtifact(topicId, "global-overview");
  return { content: artifact?.content ?? null };
}

export async function postGlobalOverviewGenerate(
  topicId: number,
): Promise<{ started?: boolean; already_running?: boolean }> {
  const res = await fetch(
    `${BASE}/api/topics/${topicId}/synthesis/global-overview/generate`,
    { method: "POST" },
  );
  return safeJson(res, {});
}

export async function fetchGlobalOverviewStatus(
  topicId: number,
): Promise<{ generating: boolean }> {
  const ts = Date.now();
  const res = await fetch(
    `${BASE}/api/topics/${topicId}/synthesis/global-overview/status?ts=${ts}`,
    { cache: "no-store" },
  );
  return safeJson(res, { generating: false }, undefined, { silent: true });
}

export async function postEvolutionReportGenerate(
  topicId: number,
): Promise<{ started?: boolean; already_running?: boolean }> {
  const res = await fetch(
    `${BASE}/api/topics/${topicId}/synthesis/evolution-report/generate`,
    { method: "POST" },
  );
  return safeJson(res, {});
}

export async function fetchEvolutionReportStatus(
  topicId: number,
): Promise<{ generating: boolean }> {
  const ts = Date.now();
  const res = await fetch(
    `${BASE}/api/topics/${topicId}/synthesis/evolution-report/status?ts=${ts}`,
    { cache: "no-store" },
  );
  return safeJson(res, { generating: false }, undefined, { silent: true });
}

export async function fetchCachedSummary(
  topicId: number,
): Promise<CachedSummary> {
  const ts = Date.now();
  const res = await fetch(`${BASE}/api/topics/${topicId}/ai-summary?ts=${ts}`, {
    cache: "no-store",
  });
  return safeJson(res, { content: null, generated_at: null }, ["content"]);
}

export async function postLiveSummaryGenerate(
  topicId: number,
  hours = 24,
): Promise<{ started: boolean; already_running?: boolean }> {
  const res = await fetch(
    `${BASE}/api/topics/${topicId}/ai-summary/generate?hours=${hours}`,
    { method: "POST" },
  );
  return safeJson(res, { started: false });
}

export async function fetchLiveSummaryStatus(
  topicId: number,
): Promise<{ generating: boolean }> {
  const ts = Date.now();
  const res = await fetch(
    `${BASE}/api/topics/${topicId}/ai-summary/status?ts=${ts}`,
    { cache: "no-store" },
  );
  return safeJson(res, { generating: false }, undefined, { silent: true });
}

export async function fetchInsightSummary(
  topicId?: number | null,
  hours = 24,
  signal?: AbortSignal,
): Promise<InsightSummary> {
  const params = new URLSearchParams({ hours: String(hours) });
  if (topicId != null) params.set("topic_id", String(topicId));
  const res = await fetchWithRetry(`${BASE}/api/insights/summary?${params}`, {
    signal,
  });
  return safeJson(
    res,
    {
      total_articles: 0,
      important_count: 0,
      source_distribution: {},
      sentiment_distribution: {},
      top_events: [],
    },
    ["total_articles", "sentiment_distribution"],
  );
}

export async function fetchTopicInsight(
  topicId?: number | null,
  window: "24h" | "7d" = "24h",
): Promise<TopicInsight> {
  const params = new URLSearchParams({ window });
  if (topicId != null) params.set("topic_id", String(topicId));
  const res = await fetch(`${BASE}/api/insights/topic?${params}`);
  return safeJson(
    res,
    {
      window_hours: 24,
      article_count: 0,
      previous_count: 0,
      trend_delta: 0,
      sentiment_distribution: {},
      top_tags: [],
    },
    ["article_count", "sentiment_distribution"],
  );
}

/** Fetch claims associated with a specific event (via evidence_sets). */
export async function fetchEventClaims(
  eventId: string,
): Promise<EventClaimSummary[]> {
  const res = await fetch(`${BASE}/api/events/${eventId}/claims`);
  return safeJson(res, { claims: [] }).then(
    (data) => (data as { claims: EventClaimSummary[] }).claims ?? [],
  );
}

/** Update the status of a claim (active | rejected | superseded). */
export async function updateClaimStatus(
  claimId: string,
  status: string,
): Promise<void> {
  await fetch(`${BASE}/api/claims/${claimId}/status`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
}

/** Permanently delete a claim. */
export async function deleteClaim(claimId: string): Promise<void> {
  await fetch(`${BASE}/api/claims/${claimId}`, { method: "DELETE" });
}
