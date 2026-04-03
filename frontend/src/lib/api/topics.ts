import { BASE, fetchWithRetry, safeJson } from "./shared";
import type {
  ResearchConfig,
  ResearchPlanTaskStatus,
  Topic,
  TopicOverview,
  TopicFeed,
  TrendingData,
  Keyword,
} from "./types";

type ApiStatusResponse = { status: string; message?: string };

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
  const res = await fetchWithRetry(`${BASE}/api/topics/reorder`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ordered_ids: orderedIds }),
  });
  const data = await safeJson(res, { status: "error", message: "Failed to reorder topics" });
  if (data.status === "error") {
    throw new Error(data.message || "Failed to reorder topics");
  }
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
): Promise<ApiStatusResponse & { id?: number }> {
  const res = await fetchWithRetry(`${BASE}/api/topics`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, color }),
  });
  return safeJson(res, { status: "error" });
}

export async function deleteTopic(id: number): Promise<ApiStatusResponse> {
  const res = await fetchWithRetry(`${BASE}/api/topics/${id}`, { method: "DELETE" });
  return safeJson(res, { status: "error" });
}

export async function archiveTopic(topicId: number): Promise<ApiStatusResponse> {
  const res = await fetchWithRetry(`${BASE}/api/topics/${topicId}/archive`, {
    method: "POST",
  });
  return safeJson(res, { status: "error" });
}

export async function unarchiveTopic(topicId: number): Promise<ApiStatusResponse> {
  const res = await fetchWithRetry(`${BASE}/api/topics/${topicId}/unarchive`, {
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
): Promise<ApiStatusResponse> {
  const res = await fetchWithRetry(`${BASE}/api/topics/${topicId}`, {
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
): Promise<ApiStatusResponse> {
  const res = await fetchWithRetry(`${BASE}/api/topics/${topicId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ research_config: JSON.stringify(config) }),
  });
  return safeJson(res, { status: "error" });
}

export async function postGenerateResearchPlan(
  topicId: number,
  prompt: string,
): Promise<{ started: boolean; already_running?: boolean }> {
  const res = await fetchWithRetry(`${BASE}/api/topics/${topicId}/generate-research-plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
  return safeJson(res, { started: false });
}

export async function fetchResearchPlanStatus(
  topicId: number,
): Promise<ResearchPlanTaskStatus> {
  const res = await fetchWithRetry(
    `${BASE}/api/topics/${topicId}/generate-research-plan/status?ts=${Date.now()}`,
    { cache: "no-store" },
  );
  return safeJson(
    res,
    {
      generating: false,
      status: "idle",
      error: null,
      result_summary: null,
      finished_at: null,
    },
    undefined,
    { silent: true },
  );
}

export async function fetchTopicFeeds(
  topicId: number,
): Promise<{ feeds: TopicFeed[] }> {
  const res = await fetchWithRetry(`${BASE}/api/topics/${topicId}/feeds`);
  return safeJson(res, { feeds: [] });
}

export async function addTopicFeed(
  topicId: number,
  feedUrl: string,
  label = "",
) {
  const res = await fetchWithRetry(`${BASE}/api/topics/${topicId}/feeds`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feed_url: feedUrl, label }),
  });
  const data = await safeJson(res, { status: "error", message: "Failed to add feed" });
  if (data.status === "error") {
    throw new Error(data.message || "Failed to add feed");
  }
}

export async function removeTopicFeed(feedId: number) {
  const res = await fetchWithRetry(`${BASE}/api/feeds/${feedId}`, { method: "DELETE" });
  const data = await safeJson(res, { status: "error", message: "Failed to remove feed" });
  if (data.status === "error") {
    throw new Error(data.message || "Failed to remove feed");
  }
}

export async function fetchKeywords(
  topicId?: number | null,
): Promise<{ keywords: Keyword[] }> {
  const params = new URLSearchParams();
  if (topicId != null) params.set("topic_id", String(topicId));
  const res = await fetchWithRetry(`${BASE}/api/keywords?${params}`);
  return safeJson(res, { keywords: [] }, ["keywords"]);
}

export async function addKeyword(
  keyword: string,
  category = "",
  topicId?: number | null,
) {
  const res = await fetchWithRetry(`${BASE}/api/keywords`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ keyword, category, topic_id: topicId ?? null }),
  });
  const data = await safeJson(res, { status: "error", message: "Failed to add keyword" });
  if (data.status === "error") {
    throw new Error(data.message || "Failed to add keyword");
  }
}

export async function removeKeyword(id: number) {
  const res = await fetchWithRetry(`${BASE}/api/keywords/${id}`, { method: "DELETE" });
  const data = await safeJson(res, { status: "error", message: "Failed to remove keyword" });
  if (data.status === "error") {
    throw new Error(data.message || "Failed to remove keyword");
  }
}
