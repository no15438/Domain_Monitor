import { BASE, fetchWithRetry, safeJson } from "./shared";
import type {
  ChatConversationPayload,
  ChatEvent,
  ChatHistoryMessage,
  ChatTaskCreateResponse,
  ChatTaskStatus,
  ConversationStreamEvent,
} from "./types";

async function parseActionResponse<T extends { status?: string; message?: string }>(
  res: Response,
  fallback: T,
  defaultMessage: string,
): Promise<T> {
  const data = await safeJson(res, fallback);
  if ((data as { status?: string }).status === "error") {
    throw new Error((data as { message?: string }).message || defaultMessage);
  }
  return data;
}

export async function createChatTask(
  message: string,
  articleContext?: string,
  topicId?: number | null,
  conversationId?: number | null,
): Promise<ChatTaskCreateResponse> {
  const res = await fetchWithRetry(`${BASE}/api/chat/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      article_context: articleContext,
      topic_id: topicId ?? null,
      conversation_id: conversationId ?? null,
    }),
  });
  return parseActionResponse(
    res,
    {
      conversation_id: 0,
      task_id: "",
      user_message_id: "",
      assistant_message_id: "",
      status: "error",
      message: "Failed to start chat task",
    },
    "Failed to start chat task",
  );
}

export async function fetchChatTaskStatus(taskId: string): Promise<ChatTaskStatus | null> {
  const res = await fetchWithRetry(`${BASE}/api/chat/tasks/${taskId}/status?ts=${Date.now()}`, {
    cache: "no-store",
  });
  if (res.status === 404) return null;
  return safeJson(
    res,
    {
      id: taskId,
      conversation_id: 0,
      assistant_message_id: "",
      status: "error",
      started_at: null,
      finished_at: null,
      error: null,
      running: false,
    },
    undefined,
    { silent: true },
  );
}

export async function fetchChatConversation(conversationId: number): Promise<ChatConversationPayload | null> {
  const res = await fetchWithRetry(`${BASE}/api/chat/conversations/${conversationId}?ts=${Date.now()}`, {
    cache: "no-store",
  });
  if (res.status === 404) return null;
  return safeJson(
    res,
    { conversation: null, messages: [], task: null },
    ["conversation", "messages", "task"],
    { silent: true },
  );
}

export async function fetchLatestChatConversationForTopic(topicId: number): Promise<ChatConversationPayload> {
  const res = await fetchWithRetry(`${BASE}/api/topics/${topicId}/chat/latest?ts=${Date.now()}`, {
    cache: "no-store",
  });
  return safeJson(
    res,
    { conversation: null, messages: [], task: null },
    ["conversation", "messages", "task"],
    { silent: true },
  );
}

export async function* streamConversation(
  conversationId: number,
  signal?: AbortSignal,
): AsyncGenerator<ConversationStreamEvent> {
  const res = await fetch(`${BASE}/api/chat/conversations/${conversationId}/stream`, {
    method: "GET",
    headers: { Accept: "text/event-stream" },
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
        if (!line.startsWith("data: ")) continue;
        try {
          const data = JSON.parse(line.slice(6)) as ConversationStreamEvent;
          yield data;
          if (data.done) return;
        } catch {
          // Skip malformed frames.
        }
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
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
        if (!line.startsWith("data: ")) continue;
        try {
          const data = JSON.parse(line.slice(6));
          if (data.done) return;
          if (data.status) yield { type: "status", value: data.status };
          if (data.content) yield { type: "content", value: data.content };
          if (data.trace) yield { type: "trace", value: data.trace };
          if (data.sources) yield { type: "sources", value: data.sources };
        } catch {
          // Skip malformed frames.
        }
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}
