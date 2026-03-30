import { BASE, fetchWithRetry, safeJson } from "./shared";
import type { Article, EventCluster, EventDetail, ClusterSource } from "./types";

export async function fetchArticles(
  limit = 50,
  offset = 0,
  topicId?: number | null,
  sort: "relevance" | "latest" = "relevance",
  status: "active" | "archived" = "active",
  eventId?: string | null,
  signal?: AbortSignal,
): Promise<{ articles: Article[]; total: number }> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
    sort,
    status,
  });
  if (topicId != null) params.set("topic_id", String(topicId));
  if (eventId != null) params.set("event_id", eventId);
  const res = await fetchWithRetry(`${BASE}/api/articles?${params}`, { signal });
  return safeJson(res, { articles: [], total: 0 }, ["articles"]);
}

export async function fetchEvents(
  topicId?: number | null,
  limit = 30,
  offset = 0,
  sort: "relevance" | "latest" = "relevance",
  status: "active" | "archived" = "active",
  signal?: AbortSignal,
): Promise<{ events: EventCluster[]; total: number }> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
    sort,
    status,
  });
  if (topicId != null) params.set("topic_id", String(topicId));
  const res = await fetchWithRetry(`${BASE}/api/events?${params}`, { signal });
  return safeJson(res, { events: [], total: 0 }, ["events"]);
}

export async function fetchEventSources(
  eventId: string,
): Promise<{ sources: ClusterSource[] }> {
  const res = await fetch(`${BASE}/api/events/${eventId}/sources`);
  return safeJson(res, { sources: [] });
}

export async function fetchEventDetail(
  eventId: string,
): Promise<{ event: EventDetail | null; sources: ClusterSource[] }> {
  const res = await fetch(`${BASE}/api/events/${eventId}`);
  return safeJson(res, { event: null, sources: [] });
}

export async function fetchChangedEvents(
  eventIds: string[],
): Promise<{ events: EventCluster[] }> {
  if (!eventIds.length) return { events: [] };
  const params = new URLSearchParams({ ids: eventIds.join(",") });
  const res = await fetchWithRetry(`${BASE}/api/events/changed?${params}`);
  return safeJson(res, { events: [] }, ["events"]);
}

export async function archiveEvent(eventId: string): Promise<boolean> {
  const res = await fetch(`${BASE}/api/events/${eventId}/archive`, { method: "PUT" });
  return res.ok;
}

export async function restoreEvent(eventId: string): Promise<boolean> {
  const res = await fetch(`${BASE}/api/events/${eventId}/restore`, { method: "PUT" });
  return res.ok;
}

export async function deleteEvent(eventId: string): Promise<boolean> {
  const res = await fetch(`${BASE}/api/events/${eventId}`, { method: "DELETE" });
  return res.ok;
}

export async function toggleEventKept(
  eventId: string,
  isKept: boolean,
): Promise<boolean> {
  const res = await fetch(`${BASE}/api/events/${eventId}/keep`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_kept: isKept ? 1 : 0 }),
  });
  return res.ok;
}

export async function toggleArticleKept(
  id: string,
  isKept: boolean,
): Promise<boolean> {
  const res = await fetch(`${BASE}/api/articles/${id}/keep`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_kept: isKept ? 1 : 0 }),
  });
  return res.ok;
}

export async function updateArticle(
  id: string,
  title: string,
  summary: string,
  tags: string[],
): Promise<boolean> {
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

export async function triggerFetch(
  topicId?: number | null,
): Promise<{ status: string }> {
  const params = new URLSearchParams();
  if (topicId != null) params.set("topic_id", String(topicId));
  const res = await fetchWithRetry(`${BASE}/api/fetch-now?${params}`, {
    method: "POST",
  });
  return safeJson(res, { status: "error" });
}

export async function fetchFetchStatus(
  topicId?: number | null,
): Promise<{
  running: boolean;
  status?: string;
  error?: string | null;
  result_summary?: string | null;
  finished_at?: string | null;
}> {
  const params = new URLSearchParams();
  if (topicId != null) params.set("topic_id", String(topicId));
  const res = await fetchWithRetry(
    `${BASE}/api/fetch-now/status?${params}&ts=${Date.now()}`,
    { cache: "no-store" },
  );
  return safeJson(
    res,
    { running: false, status: "idle", error: null, result_summary: null, finished_at: null },
    undefined,
    { silent: true },
  );
}

export interface SSEDelta {
  articles: Article[];
  impacted_event_ids: string[];
  /** Event IDs that are brand-new this fetch (not previously known) — used to auto-trigger evolution. */
  new_event_ids: string[];
}

export type SSEConnectionState =
  | "connecting"
  | "open"
  | "reconnecting"
  | "closed";

export function createSSEConnection(
  onDelta: (delta: SSEDelta) => void,
  onStateChange?: (state: SSEConnectionState) => void,
) {
  let closed = false;
  let evtSource: EventSource | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let retryAttempt = 0;
  const maxDelayMs = 15000;

  function clearReconnectTimer() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  }

  function nextDelayMs() {
    const base = Math.min(1000 * 2 ** retryAttempt, maxDelayMs);
    retryAttempt += 1;
    return base;
  }

  function connect() {
    if (closed) return;
    onStateChange?.(retryAttempt === 0 ? "connecting" : "reconnecting");
    evtSource = new EventSource(`${BASE}/api/stream`);

    evtSource.onopen = () => {
      retryAttempt = 0;
      onStateChange?.("open");
    };

    evtSource.onmessage = (event) => {
      try {
        const raw = JSON.parse(event.data);
        // New structured delta: { articles: [], impacted_event_ids: [] }
        if (raw && typeof raw === "object" && !Array.isArray(raw) && "articles" in raw) {
          onDelta({
            articles: Array.isArray(raw.articles) ? raw.articles : [],
            impacted_event_ids: Array.isArray(raw.impacted_event_ids) ? raw.impacted_event_ids : [],
            new_event_ids: Array.isArray(raw.new_event_ids) ? raw.new_event_ids : [],
          });
        } else if (Array.isArray(raw)) {
          // Legacy: plain Article[] array (backward compat)
          onDelta({ articles: raw as Article[], impacted_event_ids: [], new_event_ids: [] });
        }
      } catch {
        // keepalive or malformed frame
      }
    };

    evtSource.onerror = () => {
      evtSource?.close();
      evtSource = null;
      if (closed) return;
      onStateChange?.("reconnecting");
      clearReconnectTimer();
      reconnectTimer = setTimeout(connect, nextDelayMs());
    };
  }

  connect();

  return {
    close() {
      closed = true;
      clearReconnectTimer();
      evtSource?.close();
      evtSource = null;
      onStateChange?.("closed");
    },
  };
}
