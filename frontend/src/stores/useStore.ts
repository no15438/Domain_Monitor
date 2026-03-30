import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Article, Keyword, Topic, EventCluster } from "@/lib/api";
import {
  fetchGlobalOverview,
  fetchGlobalOverviewStatus,
  postGlobalOverviewGenerate,
  fetchCachedSummary,
  fetchLiveSummaryStatus,
  postLiveSummaryGenerate,
  fetchFetchStatus,
  fetchArticles,
} from "@/lib/api";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

export interface Toast {
  id: string;
  message: string;
  level: "error" | "warn" | "info";
}

export interface GlobalOverviewSlice {
  content: string;
  isGenerating: boolean;
}

export interface LiveSummarySlice {
  content: string;
  generatedAt: string | null;
  isGenerating: boolean;
}

const globalOverviewPollers = new Map<number, ReturnType<typeof setInterval>>();
const liveSummaryPollers = new Map<number, ReturnType<typeof setInterval>>();
// key = String(topicId ?? "null")
const fetchPollers = new Map<string, ReturnType<typeof setInterval>>();

function stopGlobalOverviewPoll(topicId: number) {
  const id = globalOverviewPollers.get(topicId);
  if (id !== undefined) {
    clearInterval(id);
    globalOverviewPollers.delete(topicId);
  }
}

function stopLiveSummaryPoll(topicId: number) {
  const id = liveSummaryPollers.get(topicId);
  if (id !== undefined) {
    clearInterval(id);
    liveSummaryPollers.delete(topicId);
  }
}

function stopFetchPoll(key: string) {
  const id = fetchPollers.get(key);
  if (id !== undefined) {
    clearInterval(id);
    fetchPollers.delete(key);
  }
}

/** Native event context for chatbot — avoids faking an Article object. */
export interface EventChatContext {
  event_id: string;
  title: string;
  summary: string;
  canonical_source: string | null;
  canonical_url: string | null;
  source_count: number;
  sentiment: string;
  importance: number;
  tags: string;
  first_seen_at: string | null;
  last_seen_at: string | null;
  /** Canonical article full text if available (loaded on-demand via fetchEventDetail) */
  canonical_content?: string | null;
  canonical_key_entities?: string | null;
  canonical_topic_analysis?: string | null;
}

interface AppState {
  topics: Topic[];
  activeTopicId: number | null;
  articles: Article[];
  keywords: Keyword[];
  /** Per-topic chat history keyed by String(topicId). Persisted to localStorage. */
  chatMessagesByTopic: Record<string, ChatMessage[]>;
  selectedArticle: Article | null;
  /** Native event chat context — preferred over selectedArticle for event cards. */
  selectedEventContext: EventChatContext | null;
  /** Currently selected event in the Knowledge panel — drives middle feed filtering. */
  selectedKnowledgeEventId: string | null;
  /** Title of the selected knowledge event (for display in filter banner). */
  selectedKnowledgeEventTitle: string | null;
  fetchingTopicId: number | null;
  isChatLoading: boolean;
  chatOpen: boolean;
  highlightedEventId: string | null;
  insightRefreshKey: number;
  globalOverviewByTopic: Record<number, GlobalOverviewSlice>;
  liveSummaryByTopic: Record<number, LiveSummarySlice>;
  toasts: Toast[];

  setTopics: (t: Topic[]) => void;
  setActiveTopicId: (id: number | null) => void;
  setArticles: (articles: Article[]) => void;
  prependArticles: (articles: Article[]) => void;
  setKeywords: (keywords: Keyword[]) => void;
  setSelectedArticle: (article: Article | null) => void;
  setSelectedEventContext: (ctx: EventChatContext | null) => void;
  setSelectedKnowledgeEvent: (id: string | null, title?: string | null) => void;
  setFetchingTopic: (id: number | null) => void;
  setChatLoading: (v: boolean) => void;
  setChatOpen: (v: boolean) => void;
  setHighlightedEventId: (id: string | null) => void;
  refreshInsights: () => void;
  addChatMessage: (msg: ChatMessage) => void;
  appendToLastAssistant: (chunk: string) => void;
  clearChat: () => void;
  addToast: (message: string, level?: Toast["level"]) => void;
  dismissToast: (id: string) => void;
  hydrateGlobalOverview: (topicId: number) => Promise<void>;
  startGlobalOverviewGeneration: (topicId: number) => Promise<void>;
  ensureGlobalOverviewPoll: (topicId: number) => void;
  hydrateLiveSummary: (topicId: number) => Promise<void>;
  startLiveSummaryGeneration: (topicId: number) => Promise<void>;
  ensureLiveSummaryPoll: (topicId: number) => void;
  hydrateFetchStatus: (topicId: number | null) => Promise<void>;
}

export const useStore = create<AppState>()(
  persist(
    (set, get) => ({
  topics: [],
  activeTopicId: null,
  articles: [],
  keywords: [],
  chatMessagesByTopic: {},
  selectedArticle: null,
  selectedEventContext: null,
  selectedKnowledgeEventId: null,
  selectedKnowledgeEventTitle: null,
  fetchingTopicId: null,
  isChatLoading: false,
  chatOpen: false,
  highlightedEventId: null,
  insightRefreshKey: 0,
  globalOverviewByTopic: {},
  liveSummaryByTopic: {},
  toasts: [],

  addToast: (message, level = "error") => {
    const id = crypto.randomUUID();
    set((s) => ({ toasts: [...s.toasts, { id, message, level }] }));
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
    }, 5000);
  },
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

  ensureLiveSummaryPoll: (topicId: number) => {
    if (liveSummaryPollers.has(topicId)) return;

    const tick = async () => {
      try {
        const [st, data] = await Promise.all([
          fetchLiveSummaryStatus(topicId),
          fetchCachedSummary(topicId),
        ]);
        const content = data.content ?? "";
        const generatedAt = data.generated_at ?? null;
        set((s) => ({
          liveSummaryByTopic: {
            ...s.liveSummaryByTopic,
            [topicId]: { content, generatedAt, isGenerating: st.generating },
          },
        }));
        if (!st.generating) {
          stopLiveSummaryPoll(topicId);
        }
      } catch {
        stopLiveSummaryPoll(topicId);
        set((s) => ({
          liveSummaryByTopic: {
            ...s.liveSummaryByTopic,
            [topicId]: {
              content: s.liveSummaryByTopic[topicId]?.content ?? "",
              generatedAt: s.liveSummaryByTopic[topicId]?.generatedAt ?? null,
              isGenerating: false,
            },
          },
        }));
      }
    };

    void tick();
    const intervalId = setInterval(() => void tick(), 2000);
    liveSummaryPollers.set(topicId, intervalId);
  },

  hydrateLiveSummary: async (topicId: number) => {
    try {
      const [data, st] = await Promise.all([
        fetchCachedSummary(topicId),
        fetchLiveSummaryStatus(topicId),
      ]);
      const content = data.content ?? "";
      const generatedAt = data.generated_at ?? null;
      set((s) => ({
        liveSummaryByTopic: {
          ...s.liveSummaryByTopic,
          [topicId]: { content, generatedAt, isGenerating: st.generating },
        },
      }));
      if (st.generating) {
        get().ensureLiveSummaryPoll(topicId);
      }
    } catch (e) {
      if (e instanceof Error && e.name !== "AbortError") {
        get().addToast("Failed to load AI analysis — retrying may help", "warn");
      }
    }
  },

  startLiveSummaryGeneration: async (topicId: number) => {
    const current = get().liveSummaryByTopic[topicId];
    if (current?.isGenerating) {
      get().ensureLiveSummaryPoll(topicId);
      return;
    }

    set((s) => ({
      liveSummaryByTopic: {
        ...s.liveSummaryByTopic,
        [topicId]: {
          content: s.liveSummaryByTopic[topicId]?.content ?? "",
          generatedAt: s.liveSummaryByTopic[topicId]?.generatedAt ?? null,
          isGenerating: true,
        },
      },
    }));

    try {
      const resp = await postLiveSummaryGenerate(topicId);
      if (resp?.already_running || resp?.started) {
        get().ensureLiveSummaryPoll(topicId);
        return;
      }
    } catch {
      set((s) => ({
        liveSummaryByTopic: {
          ...s.liveSummaryByTopic,
          [topicId]: {
            ...s.liveSummaryByTopic[topicId],
            isGenerating: false,
          },
        },
      }));
      return;
    }

    get().ensureLiveSummaryPoll(topicId);
  },

  ensureGlobalOverviewPoll: (topicId: number) => {
    if (globalOverviewPollers.has(topicId)) return;

    const tick = async () => {
      try {
        const [st, data] = await Promise.all([
          fetchGlobalOverviewStatus(topicId),
          fetchGlobalOverview(topicId),
        ]);
        const content = data.content ?? "";
        set((s) => ({
          globalOverviewByTopic: {
            ...s.globalOverviewByTopic,
            [topicId]: { content, isGenerating: st.generating },
          },
        }));
        if (!st.generating) {
          stopGlobalOverviewPoll(topicId);
        }
      } catch {
        stopGlobalOverviewPoll(topicId);
        set((s) => ({
          globalOverviewByTopic: {
            ...s.globalOverviewByTopic,
            [topicId]: {
              content: s.globalOverviewByTopic[topicId]?.content ?? "",
              isGenerating: false,
            },
          },
        }));
      }
    };

    void tick();
    const intervalId = setInterval(() => void tick(), 1500);
    globalOverviewPollers.set(topicId, intervalId);
  },

  hydrateGlobalOverview: async (topicId: number) => {
    try {
      const [data, st] = await Promise.all([
        fetchGlobalOverview(topicId),
        fetchGlobalOverviewStatus(topicId),
      ]);
      const content = data.content ?? "";
      set((s) => ({
        globalOverviewByTopic: {
          ...s.globalOverviewByTopic,
          [topicId]: { content, isGenerating: st.generating },
        },
      }));
      if (st.generating) {
        get().ensureGlobalOverviewPoll(topicId);
      }
    } catch (e) {
      if (e instanceof Error && e.name !== "AbortError") {
        get().addToast("Failed to load global overview — retrying may help", "warn");
      }
    }
  },

  startGlobalOverviewGeneration: async (topicId: number) => {
    const current = get().globalOverviewByTopic[topicId];
    if (current?.isGenerating) {
      get().ensureGlobalOverviewPoll(topicId);
      return;
    }

    set((s) => ({
      globalOverviewByTopic: {
        ...s.globalOverviewByTopic,
        [topicId]: {
          content: s.globalOverviewByTopic[topicId]?.content ?? "",
          isGenerating: true,
        },
      },
    }));

    try {
      const resp = await postGlobalOverviewGenerate(topicId);
      // Even if already_running, keep UI locked and just resume polling.
      if (resp?.already_running || resp?.started) {
        get().ensureGlobalOverviewPoll(topicId);
        return;
      }
    } catch {
      set((s) => ({
        globalOverviewByTopic: {
          ...s.globalOverviewByTopic,
          [topicId]: {
            ...s.globalOverviewByTopic[topicId],
            isGenerating: false,
          },
        },
      }));
      return;
    }

    get().ensureGlobalOverviewPoll(topicId);
  },

  hydrateFetchStatus: async (topicId: number | null) => {
    const key = String(topicId ?? "null");
    if (fetchPollers.has(key)) return; // already polling
    try {
      const { running } = await fetchFetchStatus(topicId);
      if (!running) {
        // Clear stale fetchingTopicId if it was pointing to this topic
        set((s) => s.fetchingTopicId === topicId ? { fetchingTopicId: null } : {});
        return;
      }

      // Backend fetch is still running — restore fetchingTopicId and start polling
      set({ fetchingTopicId: topicId });

      const tick = async () => {
        try {
          const st = await fetchFetchStatus(topicId);
          if (!st.running) {
            stopFetchPoll(key);
            // Refresh articles once fetch completes
            const data = await fetchArticles(50, 0, topicId);
            set((s) => ({
              fetchingTopicId: s.fetchingTopicId === topicId ? null : s.fetchingTopicId,
              articles: data.articles,
              insightRefreshKey: s.insightRefreshKey + 1,
            }));
          }
        } catch {
          stopFetchPoll(key);
          set((s) => ({
            fetchingTopicId: s.fetchingTopicId === topicId ? null : s.fetchingTopicId,
          }));
        }
      };

      const intervalId = setInterval(() => void tick(), 2000);
      fetchPollers.set(key, intervalId);
    } catch (e) {
      if (e instanceof Error && e.name !== "AbortError") {
        get().addToast("Failed to check fetch status", "warn");
      }
    }
  },

  setTopics: (topics) => set({ topics }),
  setActiveTopicId: (id) => {
    const prev = get().activeTopicId;
    if (prev != null && prev !== id) {
      stopGlobalOverviewPoll(prev);
      stopLiveSummaryPoll(prev);
      stopFetchPoll(String(prev));
    }
    set({ activeTopicId: id, highlightedEventId: null, selectedKnowledgeEventId: null, selectedKnowledgeEventTitle: null });
  },
  setArticles: (articles) => set({ articles }),
  prependArticles: (newArticles) =>
    set((s) => {
      const existingIds = new Set(s.articles.map((a) => a.id));
      const unique = newArticles.filter((a) => !existingIds.has(a.id));
      return { articles: [...unique, ...s.articles] };
    }),
  setKeywords: (keywords) => set({ keywords }),
  setSelectedArticle: (article) => set({ selectedArticle: article, selectedEventContext: null }),
  setSelectedEventContext: (ctx) => set({ selectedEventContext: ctx, selectedArticle: null }),
  setSelectedKnowledgeEvent: (id, title = null) => set({ selectedKnowledgeEventId: id, selectedKnowledgeEventTitle: id ? (title ?? null) : null }),
  setFetchingTopic: (id) => set({ fetchingTopicId: id }),
  setChatLoading: (v) => set({ isChatLoading: v }),
  setChatOpen: (v) => set({ chatOpen: v }),
  setHighlightedEventId: (id) => set({ highlightedEventId: id }),
  refreshInsights: () => set((s) => ({ insightRefreshKey: s.insightRefreshKey + 1 })),
  addChatMessage: (msg) =>
    set((s) => {
      const key = String(s.activeTopicId ?? "null");
      const prev = s.chatMessagesByTopic[key] ?? [];
      return { chatMessagesByTopic: { ...s.chatMessagesByTopic, [key]: [...prev, msg] } };
    }),
  appendToLastAssistant: (chunk) =>
    set((s) => {
      const key = String(s.activeTopicId ?? "null");
      const msgs = [...(s.chatMessagesByTopic[key] ?? [])];
      const last = msgs[msgs.length - 1];
      if (last && last.role === "assistant") {
        msgs[msgs.length - 1] = { ...last, content: last.content + chunk };
      }
      return { chatMessagesByTopic: { ...s.chatMessagesByTopic, [key]: msgs } };
    }),
  clearChat: () =>
    set((s) => {
      const key = String(s.activeTopicId ?? "null");
      return {
        chatMessagesByTopic: { ...s.chatMessagesByTopic, [key]: [] },
        selectedArticle: null,
      };
    }),
    }),
    {
      name: "domain-monitor-chat",
      partialize: (state) => ({ chatMessagesByTopic: state.chatMessagesByTopic }),
    }
  )
);
