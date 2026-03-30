import { BASE, fetchWithRetry, safeJson } from "./shared";
import type {
  ResearchConfig,
  ResearchPlan,
  Topic,
  TopicOverview,
  TopicFeed,
  TrendingData,
  Keyword,
} from "./types";

export async function fetchTopics(): Promise<{ topics: Topic[] }> {
  const res = await fetchWithRetry(`${BASE}/api/topics`);
  return safeJson(res, { topics: [] }, ["topics"]);
}

export async function fetchTopicsOverview(
  hours = 24,
): Promise<{ topics: TopicOverview[] }> {
  const res = await fetchWithRetry(`${BASE}/api/topics/overview?hours=${hours}`);
  return safeJson(res, { topics: [] }, ["topics"]);
}

export async function fetchArchivedTopicsOverview(
  hours = 24,
): Promise<{ topics: TopicOverview[] }> {
  const res = await fetchWithRetry(
    `${BASE}/api/topics/archived/overview?hours=${hours}`,
  );
  return safeJson(res, { topics: [] }, ["topics"]);
}

export async function reorderTopics(orderedIds: number[]): Promise<void> {
  await fetch(`${BASE}/api/topics/reorder`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ordered_ids: orderedIds }),
  });
}

export async function fetchTrending(
  topicId: number,
  days = 7,
): Promise<TrendingData> {
  const res = await fetchWithRetry(
    `${BASE}/api/topics/${topicId}/trending?days=${days}`,
  );
  return safeJson(res, {
    days: 7,
    daily: [],
    top_entities: [],
    avg_topic_relevance: 0,
  });
}

export async function createTopic(
  name: string,
  color = "#6366f1",
): Promise<{ status: string; id?: number; message?: string }> {
  const res = await fetch(`${BASE}/api/topics`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, color }),
  });
  return safeJson(res, { status: "error" });
}

export async function deleteTopic(id: number) {
  const res = await fetch(`${BASE}/api/topics/${id}`, { method: "DELETE" });
  return safeJson(res, { status: "error" });
}

export async function archiveTopic(topicId: number) {
  const res = await fetch(`${BASE}/api/topics/${topicId}/archive`, {
    method: "POST",
  });
  return safeJson(res, { status: "error" });
}

export async function unarchiveTopic(topicId: number) {
  const res = await fetch(`${BASE}/api/topics/${topicId}/unarchive`, {
    method: "POST",
  });
  return safeJson(res, { status: "error" });
}

export async function updateTopic(
  topicId: number,
  patch: {
    name?: string;
    color?: string;
    research_brief?: string;
    research_config?: string;
  },
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

export async function updateResearchConfig(
  topicId: number,
  config: ResearchConfig,
) {
  const res = await fetch(`${BASE}/api/topics/${topicId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ research_config: JSON.stringify(config) }),
  });
  return safeJson(res, { status: "error" });
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

export async function fetchTopicFeeds(
  topicId: number,
): Promise<{ feeds: TopicFeed[] }> {
  const res = await fetch(`${BASE}/api/topics/${topicId}/feeds`);
  return safeJson(res, { feeds: [] });
}

export async function addTopicFeed(
  topicId: number,
  feedUrl: string,
  label = "",
) {
  await fetch(`${BASE}/api/topics/${topicId}/feeds`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feed_url: feedUrl, label }),
  });
}

export async function removeTopicFeed(feedId: number) {
  await fetch(`${BASE}/api/feeds/${feedId}`, { method: "DELETE" });
}

export async function fetchKeywords(
  topicId?: number | null,
): Promise<{ keywords: Keyword[] }> {
  const params = new URLSearchParams();
  if (topicId != null) params.set("topic_id", String(topicId));
  const res = await fetch(`${BASE}/api/keywords?${params}`);
  return safeJson(res, { keywords: [] }, ["keywords"]);
}

export async function addKeyword(
  keyword: string,
  category = "",
  topicId?: number | null,
) {
  await fetch(`${BASE}/api/keywords`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ keyword, category, topic_id: topicId ?? null }),
  });
}

export async function removeKeyword(id: number) {
  await fetch(`${BASE}/api/keywords/${id}`, { method: "DELETE" });
}
