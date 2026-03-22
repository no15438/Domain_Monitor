export interface Article {
  id: string;
  title: string;
  summary: string;
  content: string;
  source: string;
  url: string;
  tags: string;
  sentiment: "positive" | "negative" | "neutral";
  importance: number;
  source_type: string;
  topic_id: number | null;
  published_at: string;
  created_at: string;
  event_id: string;
  is_canonical: number;
  event_size: number;
  source_score: number;
  source_breakdown: string;
  topic_relevance: number;
  key_entities: string;
  topic_analysis: string;
  is_kept?: number;
  status?: "active" | "archived";
}

export interface TrendingDay {
  day: string;
  total: number;
  positive: number;
  neutral: number;
  negative: number;
  avg_importance: number;
  avg_relevance: number;
}

export interface TrendingData {
  days: number;
  daily: TrendingDay[];
  top_entities: { entity: string; count: number }[];
  avg_topic_relevance: number;
}

export interface Keyword {
  id: number;
  keyword: string;
  category: string;
  topic_id: number | null;
  is_active: number;
  created_at: string;
}

export interface ResearchConfig {
  angles: string[];
  entities: string[];
  geographic_scope: string[];
  sector_scope: string[];
}

export interface Topic {
  id: number;
  name: string;
  color: string;
  research_brief?: string;
  research_config?: string; // JSON string of ResearchConfig
  is_active: number;
  created_at: string;
}

export function parseResearchConfig(topic: Topic): ResearchConfig {
  const empty: ResearchConfig = { angles: [], entities: [], geographic_scope: [], sector_scope: [] };
  if (!topic.research_config) return empty;
  try { return { ...empty, ...JSON.parse(topic.research_config) }; }
  catch { return empty; }
}

export interface TopicOverview extends Topic {
  article_count: number;
  important_count: number;
  sentiment: Record<string, number>;
  trend_delta: number;
  keywords: string[];
  top_headline: string | null;
}

const BASE =
  typeof window !== "undefined" && process.env.NEXT_PUBLIC_API_BASE
    ? process.env.NEXT_PUBLIC_API_BASE
    : "http://localhost:8000";

const DEV = process.env.NODE_ENV === "development";

function apiWarn(msg: string, ...args: unknown[]) {
  if (DEV) console.warn(`[api] ${msg}`, ...args);
}

/**
 * Wraps fetch with automatic retry on 5xx or network errors.
 * Uses exponential backoff: 1s, then 3s. Non-retryable on 4xx.
 */
export async function fetchWithRetry(
  url: string,
  options?: RequestInit,
  maxRetries = 2,
): Promise<Response> {
  const delays = [1000, 3000];
  let lastError: unknown;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const res = await fetch(url, options);
      if (res.ok || (res.status >= 400 && res.status < 500)) return res;
      lastError = new Error(`HTTP ${res.status}`);
    } catch (e) {
      lastError = e;
      if (options?.signal?.aborted) throw e;
    }
    if (attempt < maxRetries) {
      await new Promise((r) => setTimeout(r, delays[attempt] ?? 3000));
    }
  }
  throw lastError;
}

/** Lazy import of toast emitter — avoids circular imports at module level. */
function emitToast(message: string, level: "error" | "warn" | "info" = "error") {
  try {
    // Dynamic require avoids circular reference since store imports from api
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { useStore } = require("@/stores/useStore");
    useStore.getState().addToast(message, level);
  } catch {
    /* store not ready yet — swallow */
  }
}

async function safeJson<T>(
  res: Response,
  fallback: T,
  shape?: (keyof NonNullable<T & object>)[],
  options?: { silent?: boolean },
): Promise<T> {
  if (!res.ok) {
    apiWarn(`${res.url} → HTTP ${res.status}`);
    if (!options?.silent && res.status >= 500) {
      emitToast(`Server error (${res.status}) — please try again later`);
    }
    return fallback;
  }
  let data: T;
  try {
    data = await res.json();
  } catch (e) {
    apiWarn(`${res.url} → invalid JSON`, e);
    if (!options?.silent) emitToast("Received invalid response from server", "warn");
    return fallback;
  }
  if (shape && data != null && typeof data === "object") {
    const missing = shape.filter((k) => !(k in (data as object)));
    if (missing.length > 0) {
      apiWarn(`${res.url} → response missing fields: ${missing.join(", ")}`, data);
    }
  }
  return data;
}

// ── Topics ───────────────────────────────────────────

export async function fetchTopics(): Promise<{ topics: Topic[] }> {
  const res = await fetchWithRetry(`${BASE}/api/topics`);
  return safeJson(res, { topics: [] }, ["topics"]);
}

export async function fetchTopicsOverview(hours = 24): Promise<{ topics: TopicOverview[] }> {
  const res = await fetchWithRetry(`${BASE}/api/topics/overview?hours=${hours}`);
  return safeJson(res, { topics: [] }, ["topics"]);
}

export async function fetchTrending(topicId: number, days = 7): Promise<TrendingData> {
  const res = await fetchWithRetry(`${BASE}/api/topics/${topicId}/trending?days=${days}`);
  return safeJson(res, { days: 7, daily: [], top_entities: [], avg_topic_relevance: 0 });
}

export async function createTopic(name: string, color = "#6366f1") {
  const res = await fetch(`${BASE}/api/topics`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, color }),
  });
  return safeJson(res, { status: "error" });
}

export async function deleteTopic(id: number) {
  await fetch(`${BASE}/api/topics/${id}`, { method: "DELETE" });
}

export async function updateTopic(
  topicId: number,
  patch: { name?: string; color?: string; research_brief?: string; research_config?: string }
) {
  const res = await fetch(`${BASE}/api/topics/${topicId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return safeJson(res, { status: "error" });
}

export async function updateTopicBrief(topicId: number, brief: string) {
  return updateTopic(topicId, { research_brief: brief });
}

export async function updateResearchConfig(topicId: number, config: ResearchConfig) {
  const res = await fetch(`${BASE}/api/topics/${topicId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ research_config: JSON.stringify(config) }),
  });
  return safeJson(res, { status: "error" });
}

export interface ResearchPlan {
  research_brief: string;
  keywords: string[];
  rss_feeds: { id?: number; url: string; label: string }[];
  angles: string[];
  entities: string[];
  geographic_scope: string[];
  sector_scope: string[];
}

export async function generateResearchPlan(
  topicId: number,
  prompt: string,
): Promise<{ status: string; plan?: ResearchPlan; message?: string }> {
  const res = await fetch(`${BASE}/api/topics/${topicId}/generate-research-plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
  return safeJson(res, { status: "error", message: "Network error" });
}

// ── Topic Feeds ──────────────────────────────────────

export interface TopicFeed {
  id: number;
  topic_id: number;
  feed_url: string;
  label: string;
  is_active: number;
  created_at: string;
}

export async function fetchTopicFeeds(topicId: number): Promise<{ feeds: TopicFeed[] }> {
  const res = await fetch(`${BASE}/api/topics/${topicId}/feeds`);
  return safeJson(res, { feeds: [] });
}

export async function addTopicFeed(topicId: number, feedUrl: string, label = "") {
  await fetch(`${BASE}/api/topics/${topicId}/feeds`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feed_url: feedUrl, label }),
  });
}

export async function removeTopicFeed(feedId: number) {
  await fetch(`${BASE}/api/feeds/${feedId}`, { method: "DELETE" });
}

// ── Articles ─────────────────────────────────────────

export async function fetchArticles(
  limit = 50,
  offset = 0,
  topicId?: number | null,
  sort: "relevance" | "latest" = "relevance",
  status: "active" | "archived" = "active",
  signal?: AbortSignal,
): Promise<{ articles: Article[]; total: number }> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset), sort, status });
  if (topicId != null) params.set("topic_id", String(topicId));
  const res = await fetchWithRetry(`${BASE}/api/articles?${params}`, { signal });
  return safeJson(res, { articles: [], total: 0 }, ["articles"]);
}

// ── Keywords ─────────────────────────────────────────

export async function fetchKeywords(
  topicId?: number | null
): Promise<{ keywords: Keyword[] }> {
  const params = new URLSearchParams();
  if (topicId != null) params.set("topic_id", String(topicId));
  const res = await fetch(`${BASE}/api/keywords?${params}`);
  return safeJson(res, { keywords: [] }, ["keywords"]);
}

export async function addKeyword(keyword: string, category = "", topicId?: number | null) {
  await fetch(`${BASE}/api/keywords`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ keyword, category, topic_id: topicId ?? null }),
  });
}

export async function removeKeyword(id: number) {
  await fetch(`${BASE}/api/keywords/${id}`, { method: "DELETE" });
}

// ── Fetch ────────────────────────────────────────────

export async function triggerFetch(topicId?: number | null): Promise<{ status: string }> {
  const params = new URLSearchParams();
  if (topicId != null) params.set("topic_id", String(topicId));
  const res = await fetch(`${BASE}/api/fetch-now?${params}`, { method: "POST" });
  return safeJson(res, { status: "error" });
}

export async function fetchFetchStatus(topicId?: number | null): Promise<{ running: boolean }> {
  const params = new URLSearchParams();
  if (topicId != null) params.set("topic_id", String(topicId));
  const res = await fetch(`${BASE}/api/fetch-now/status?${params}&ts=${Date.now()}`, { cache: "no-store" });
  return safeJson(res, { running: false }, undefined, { silent: true });
}

// ── Chat ─────────────────────────────────────────────

export type ChatEvent =
  | { type: "status"; value: string }
  | { type: "content"; value: string };

export interface ChatHistoryMessage {
  role: "user" | "assistant";
  content: string;
}

export async function* streamChat(
  message: string,
  articleContext?: string,
  topicId?: number | null,
  signal?: AbortSignal,
  history?: ChatHistoryMessage[],
): AsyncGenerator<ChatEvent> {
  const res = await fetch(`${BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      article_context: articleContext,
      topic_id: topicId ?? null,
      history: history ?? [],
    }),
    signal,
  });

  if (!res.ok || !res.body) return;

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      if (signal?.aborted) break;
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.done) return;
            if (data.status) yield { type: "status", value: data.status };
            if (data.content) yield { type: "content", value: data.content };
          } catch {
            /* skip malformed */
          }
        }
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}

// ── Knowledge Base ──────────────────────────────────

export interface Snapshot {
  id: number;
  topic_id: number;
  overview_content: string;
  stats_metadata: string;
  created_at: string;
}

export async function fetchSnapshots(topicId: number): Promise<Snapshot[]> {
  const res = await fetch(`${BASE}/api/topics/${topicId}/snapshots`);
  return safeJson(res, []);
}

export async function updateSnapshot(id: number, content: string): Promise<boolean> {
  const res = await fetch(`${BASE}/api/snapshots/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  return res.ok;
}

export async function deleteSnapshot(id: number, topicId: number): Promise<boolean> {
  const res = await fetch(`${BASE}/api/snapshots/${id}?topic_id=${topicId}`, {
    method: "DELETE",
  });
  return res.ok;
}

export async function fetchKeptArticles(topicId: number): Promise<Article[]> {
  const res = await fetch(`${BASE}/api/topics/${topicId}/kept-articles`);
  return safeJson(res, []);
}

export async function toggleArticleKept(id: string, isKept: boolean): Promise<boolean> {
  const res = await fetch(`${BASE}/api/articles/${id}/keep`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_kept: isKept ? 1 : 0 }),
  });
  return res.ok;
}

export async function updateArticle(id: string, title: string, summary: string, tags: string[]): Promise<boolean> {
  const res = await fetch(`${BASE}/api/articles/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, summary, tags }),
  });
  return res.ok;
}

export async function patchArticle(
  id: string,
  patch: { sentiment?: string; importance?: number },
): Promise<boolean> {
  const res = await fetch(`${BASE}/api/articles/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return res.ok;
}

export async function deleteArticle(id: string): Promise<boolean> {
  const res = await fetch(`${BASE}/api/articles/${id}`, {
    method: "DELETE",
  });
  return res.ok;
}

export async function archiveArticle(id: string): Promise<boolean> {
  const res = await fetch(`${BASE}/api/articles/${id}/archive`, {
    method: "PUT",
  });
  return res.ok;
}

export async function restoreArticle(id: string): Promise<boolean> {
  const res = await fetch(`${BASE}/api/articles/${id}/restore`, {
    method: "PUT",
  });
  return res.ok;
}

// ── Global Overview ─────────────────────────────────

export async function fetchGlobalOverview(topicId: number): Promise<{ content: string | null }> {
  const ts = Date.now();
  const res = await fetch(`${BASE}/api/topics/${topicId}/global-overview?ts=${ts}`, { cache: "no-store" });
  return safeJson(res, { content: null });
}

/** Starts background generation on the server; completion persists even if the UI closes. */
export async function postGlobalOverviewGenerate(topicId: number): Promise<{
  started?: boolean;
  already_running?: boolean;
}> {
  const res = await fetch(`${BASE}/api/topics/${topicId}/global-overview/generate`, {
    method: "POST",
  });
  return safeJson(res, {});
}

export async function fetchGlobalOverviewStatus(topicId: number): Promise<{ generating: boolean }> {
  const ts = Date.now();
  const res = await fetch(`${BASE}/api/topics/${topicId}/global-overview/status?ts=${ts}`, { cache: "no-store" });
  return safeJson(res, { generating: false }, undefined, { silent: true });
}

// ── AI Topic Summary ────────────────────────────────

export interface CachedSummary {
  content: string | null;
  generated_at: string | null;
  snapshot_id?: number | null;
  stats_metadata?: string | null;
}

export async function fetchCachedSummary(topicId: number): Promise<CachedSummary> {
  const ts = Date.now();
  const res = await fetch(`${BASE}/api/topics/${topicId}/ai-summary?ts=${ts}`, { cache: "no-store" });
  return safeJson(res, { content: null, generated_at: null }, ["content"]);
}

export async function postLiveSummaryGenerate(
  topicId: number,
  hours = 24
): Promise<{ started: boolean; already_running?: boolean }> {
  const res = await fetch(`${BASE}/api/topics/${topicId}/ai-summary/generate?hours=${hours}`, {
    method: "POST",
  });
  return safeJson(res, { started: false });
}

export async function fetchLiveSummaryStatus(
  topicId: number
): Promise<{ generating: boolean }> {
  const ts = Date.now();
  const res = await fetch(`${BASE}/api/topics/${topicId}/ai-summary/status?ts=${ts}`, { cache: "no-store" });
  return safeJson(res, { generating: false }, undefined, { silent: true });
}

// ── Insights ────────────────────────────────────────

export interface InsightSummary {
  total_articles: number;
  important_count: number;
  source_distribution: Record<string, number>;
  sentiment_distribution: Record<string, number>;
  top_events: Article[];
}

export interface TopicInsight {
  window_hours: number;
  article_count: number;
  previous_count: number;
  trend_delta: number;
  sentiment_distribution: Record<string, number>;
  top_tags: { tag: string; count: number }[];
}

export async function fetchInsightSummary(
  topicId?: number | null,
  hours = 24,
  signal?: AbortSignal,
): Promise<InsightSummary> {
  const params = new URLSearchParams({ hours: String(hours) });
  if (topicId != null) params.set("topic_id", String(topicId));
  const res = await fetchWithRetry(`${BASE}/api/insights/summary?${params}`, { signal });
  return safeJson(res, {
    total_articles: 0,
    important_count: 0,
    source_distribution: {},
    sentiment_distribution: {},
    top_events: [],
  }, ["total_articles", "sentiment_distribution"]);
}

export async function fetchTopicInsight(
  topicId?: number | null,
  window: "24h" | "7d" = "24h"
): Promise<TopicInsight> {
  const params = new URLSearchParams({ window });
  if (topicId != null) params.set("topic_id", String(topicId));
  const res = await fetch(`${BASE}/api/insights/topic?${params}`);
  return safeJson(res, {
    window_hours: 24,
    article_count: 0,
    previous_count: 0,
    trend_delta: 0,
    sentiment_distribution: {},
    top_tags: [],
  }, ["article_count", "sentiment_distribution"]);
}

export async function fetchEvents(
  topicId?: number | null,
  limit = 30,
  offset = 0,
  sort: "relevance" | "latest" = "relevance",
  status: "active" | "archived" = "active",
  signal?: AbortSignal,
): Promise<{ events: Article[]; total: number }> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset), sort, status });
  if (topicId != null) params.set("topic_id", String(topicId));
  const res = await fetchWithRetry(`${BASE}/api/events?${params}`, { signal });
  return safeJson(res, { events: [], total: 0 }, ["events"]);
}

export async function fetchEventAlternatives(
  eventId: string
): Promise<{ articles: Article[] }> {
  const res = await fetch(`${BASE}/api/events/${eventId}`);
  return safeJson(res, { articles: [] });
}

// ── SSE ──────────────────────────────────────────────

/**
 * Creates an SSE connection with automatic reconnection.
 * Call `.close()` on the returned handle to permanently disconnect.
 */
export function createSSEConnection(onArticles: (articles: Article[]) => void) {
  let closed = false;
  let evtSource: EventSource | null = null;

  function connect() {
    if (closed) return;
    evtSource = new EventSource(`${BASE}/api/stream`);

    evtSource.onmessage = (event) => {
      try {
        const articles: Article[] = JSON.parse(event.data);
        onArticles(articles);
      } catch {
        /* keepalive or malformed */
      }
    };

    evtSource.onerror = () => {
      evtSource?.close();
      evtSource = null;
      if (!closed) setTimeout(connect, 5000);
    };
  }

  connect();

  return {
    close() {
      closed = true;
      evtSource?.close();
      evtSource = null;
    },
  };
}
