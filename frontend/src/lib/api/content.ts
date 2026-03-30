import { BASE, fetchWithRetry, safeJson } from "./shared";
import type { Article } from "./types";

export async function fetchArticles(
  limit = 50,
  offset = 0,
  topicId?: number | null,
  sort: "relevance" | "latest" = "relevance",
  status: "active" | "archived" = "active",
  signal?: AbortSignal,
): Promise<{ articles: Article[]; total: number }> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
    sort,
    status,
  });
  if (topicId != null) params.set("topic_id", String(topicId));
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
): Promise<{ events: Article[]; total: number }> {
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

export async function fetchEventAlternatives(
  eventId: string,
): Promise<{ articles: Article[] }> {
  const res = await fetch(`${BASE}/api/events/${eventId}`);
  return safeJson(res, { articles: [] });
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
  const res = await fetch(`${BASE}/api/fetch-now?${params}`, {
    method: "POST",
  });
  return safeJson(res, { status: "error" });
}

export async function fetchFetchStatus(
  topicId?: number | null,
): Promise<{ running: boolean }> {
  const params = new URLSearchParams();
  if (topicId != null) params.set("topic_id", String(topicId));
  const res = await fetch(
    `${BASE}/api/fetch-now/status?${params}&ts=${Date.now()}`,
    { cache: "no-store" },
  );
  return safeJson(res, { running: false }, undefined, { silent: true });
}

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
        // keepalive or malformed frame
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
