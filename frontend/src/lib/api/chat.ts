import { BASE } from "./shared";
import type { ChatEvent, ChatHistoryMessage } from "./types";

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
