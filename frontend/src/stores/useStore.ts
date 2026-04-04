import { create } from "zustand";
import { persist } from "zustand/middleware";
import type {
  AnalysisCitation,
  Article,
  ChatConversationMessage,
  ChatConversationPayload,
  Keyword,
  Topic,
  EventCluster,
  ChatTaskStatus as PersistedChatTaskStatus,
  ConversationStreamEvent,
  WorkspacePane,
} from "@/lib/api";
import {
  createChatTask as apiCreateChatTask,
  fetchChatConversation,
  fetchChatTaskStatus,
  fetchLatestChatConversationForTopic,
  fetchGlobalOverview,
  fetchGlobalOverviewStatus,
  postGlobalOverviewGenerate,
  fetchCachedSummary,
  fetchLiveSummaryStatus,
  postLiveSummaryGenerate,
  fetchFetchStatus,
  fetchArticles,
  fetchResearchPlanStatus,
  postGenerateResearchPlan,
} from "@/lib/api";

export type ChatMessage = ChatConversationMessage;

export interface TopicChatTaskSlice {
  taskId: string;
  conversationId: number;
  assistantMessageId: string;
  status: PersistedChatTaskStatus["status"];
  running: boolean;
  error: string | null;
  startedAt: string | null;
  finishedAt: string | null;
}

export interface Toast {
  id: string;
  message: string;
  level: "error" | "warn" | "info";
}

export interface GlobalOverviewSlice {
  content: string;
  citations?: AnalysisCitation[];
  isGenerating: boolean;
  lastStatus?: string;
  lastError?: string | null;
}

export interface LiveSummarySlice {
  content: string;
  generatedAt: string | null;
  citations?: AnalysisCitation[];
  isGenerating: boolean;
  lastStatus?: string;
  lastError?: string | null;
}

export type ActionStatus = "idle" | "running" | "success" | "error";

export interface ActionState {
  status: ActionStatus;
  startedAt: number | null;
  finishedAt: number | null;
  error: string | null;
  result: string | null;
}

export interface EventFeedPrefs {
  sentimentFilter: "all" | "positive" | "neutral" | "negative";
  sortMode: "relevance" | "latest";
  showArchived: boolean;
}

export interface ResearchPlanTaskSlice {
  isGenerating: boolean;
  lastStatus?: string;
  lastError?: string | null;
  finishedAt?: string | null;
}

const globalOverviewPollers = new Map<number, ReturnType<typeof setInterval>>();
const liveSummaryPollers = new Map<number, ReturnType<typeof setInterval>>();
const researchPlanPollers = new Map<number, ReturnType<typeof setInterval>>();
const chatTaskPollers = new Map<string, ReturnType<typeof setInterval>>();

function chatTopicKey(topicId: number | null) {
  return String(topicId ?? "null");
}

function stopChatTaskPoll(topicId: number | null) {
  const key = chatTopicKey(topicId);
  const timer = chatTaskPollers.get(key);
  if (timer) {
    clearInterval(timer);
    chatTaskPollers.delete(key);
  }
}

function replaceTrace(
  traces: ChatMessage["trace"] | undefined,
  trace: NonNullable<ConversationStreamEvent["trace"]>,
): ChatMessage["trace"] {
  const current = [...(traces ?? [])];
  const idx = current.findIndex((item) => item.kind === trace.kind);
  if (idx >= 0) current[idx] = trace;
  else current.push(trace);
  return current;
}

function toTopicChatTask(task: PersistedChatTaskStatus | null): TopicChatTaskSlice | null {
  if (!task) return null;
  return {
    taskId: task.id,
    conversationId: task.conversation_id,
    assistantMessageId: task.assistant_message_id,
    status: task.status,
    running: task.running,
    error: task.error,
    startedAt: task.started_at,
    finishedAt: task.finished_at,
  };
}
// key = String(topicId ?? "null")
const fetchPollers = new Map<string, ReturnType<typeof setInterval>>();
const taskNotifications = new Map<string, string>();

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

function stopResearchPlanPoll(topicId: number) {
  const id = researchPlanPollers.get(topicId);
  if (id !== undefined) {
    clearInterval(id);
    researchPlanPollers.delete(topicId);
  }
}

function stopFetchPoll(key: string) {
  const id = fetchPollers.get(key);
  if (id !== undefined) {
    clearInterval(id);
    fetchPollers.delete(key);
  }
}

function notifyTaskOutcome(
  key: string,
  status: string | undefined,
  error: string | null | undefined,
  resultSummary: string | null | undefined,
  addToast: (message: string, level?: Toast["level"]) => void,
) {
  const marker = `${status || "unknown"}|${error || ""}|${resultSummary || ""}`;
  if (taskNotifications.get(key) === marker) return;
  taskNotifications.set(key, marker);

  if (status === "error") {
    addToast(error || "Background task failed", "error");
    return;
  }
  if (status === "done" && resultSummary) {
    addToast(resultSummary, "info");
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
  chatConversationIdByTopic: Record<string, number | null>;
  chatTaskByTopic: Record<string, TopicChatTaskSlice | null>;
  chatMessagesByConversation: Record<string, ChatMessage[]>;
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
  actionStates: Record<string, ActionState>;
  analysisTabByTopic: Record<number, "realtime" | "overview">;
  analysisWindowByTopic: Record<number, "24h" | "7d">;
  briefCollapsedByTopic: Record<number, boolean>;
  mobilePaneByTopic: Record<number, WorkspacePane>;
  eventFeedPrefsByTopic: Record<number, EventFeedPrefs>;
  researchPlanDraftByTopic: Record<number, string>;
  researchPlanByTopic: Record<number, ResearchPlanTaskSlice>;
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
  clearChat: () => void;
  hydrateChatConversation: (topicId: number | null) => Promise<void>;
  startChatTask: (message: string, articleContext?: string) => Promise<void>;
  ensureChatTaskPoll: (topicId: number | null) => void;
  applyChatConversationPayload: (topicId: number | null, payload: ChatConversationPayload | null) => void;
  applyChatStreamEvent: (conversationId: number, event: ConversationStreamEvent) => void;
  addToast: (message: string, level?: Toast["level"]) => void;
  dismissToast: (id: string) => void;
  hydrateGlobalOverview: (topicId: number) => Promise<void>;
  startGlobalOverviewGeneration: (topicId: number) => Promise<void>;
  ensureGlobalOverviewPoll: (topicId: number) => void;
  hydrateLiveSummary: (topicId: number) => Promise<void>;
  startLiveSummaryGeneration: (topicId: number) => Promise<void>;
  ensureLiveSummaryPoll: (topicId: number) => void;
  hydrateFetchStatus: (topicId: number | null) => Promise<void>;
  beginAction: (key: string) => void;
  endAction: (key: string, status: Exclude<ActionStatus, "running">, error?: string | null, result?: string | null) => void;
  setActionRunning: (key: string, running: boolean) => void;
  getActionState: (key: string) => ActionState;
  clearActionState: (key: string) => void;
  setAnalysisTab: (topicId: number, tab: "realtime" | "overview") => void;
  setAnalysisWindow: (topicId: number, window: "24h" | "7d") => void;
  setBriefCollapsed: (topicId: number, collapsed: boolean) => void;
  setMobilePane: (topicId: number, pane: WorkspacePane) => void;
  setEventFeedPrefs: (topicId: number, patch: Partial<EventFeedPrefs>) => void;
  setResearchPlanDraft: (topicId: number, prompt: string) => void;
  hydrateResearchPlanStatus: (topicId: number) => Promise<void>;
  startResearchPlanGeneration: (topicId: number, prompt: string) => Promise<void>;
  ensureResearchPlanPoll: (topicId: number) => void;
}

function defaultActionState(): ActionState {
  return {
    status: "idle",
    startedAt: null,
    finishedAt: null,
    error: null,
    result: null,
  };
}

function defaultEventFeedPrefs(): EventFeedPrefs {
  return {
    sentimentFilter: "all",
    sortMode: "relevance",
    showArchived: false,
  };
}

export const useStore = create<AppState>()(
  persist(
    (set, get) => ({
  topics: [],
  activeTopicId: null,
  articles: [],
  keywords: [],
  chatConversationIdByTopic: {},
  chatTaskByTopic: {},
  chatMessagesByConversation: {},
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
  actionStates: {},
  analysisTabByTopic: {},
  analysisWindowByTopic: {},
  briefCollapsedByTopic: {},
  mobilePaneByTopic: {},
  eventFeedPrefsByTopic: {},
  researchPlanDraftByTopic: {},
  researchPlanByTopic: {},
  toasts: [],

  addToast: (message, level = "error") => {
    const id = crypto.randomUUID();
    set((s) => ({ toasts: [...s.toasts, { id, message, level }] }));
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
    }, 5000);
  },
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

  beginAction: (key) =>
    set((s) => ({
      actionStates: {
        ...s.actionStates,
        [key]: {
          status: "running",
          startedAt: Date.now(),
          finishedAt: null,
          error: null,
          result: null,
        },
      },
    })),
  endAction: (key, status, error = null, result = null) =>
    set((s) => ({
      actionStates: {
        ...s.actionStates,
        [key]: {
          status,
          startedAt: s.actionStates[key]?.startedAt ?? Date.now(),
          finishedAt: Date.now(),
          error,
          result,
        },
      },
    })),
  setActionRunning: (key, running) =>
    running ? get().beginAction(key) : get().endAction(key, "success"),
  getActionState: (key) => get().actionStates[key] ?? defaultActionState(),
  clearActionState: (key) =>
    set((s) => {
      const next = { ...s.actionStates };
      delete next[key];
      return { actionStates: next };
    }),
  setAnalysisTab: (topicId, tab) =>
    set((s) => ({ analysisTabByTopic: { ...s.analysisTabByTopic, [topicId]: tab } })),
  setAnalysisWindow: (topicId, window) =>
    set((s) => ({ analysisWindowByTopic: { ...s.analysisWindowByTopic, [topicId]: window } })),
  setBriefCollapsed: (topicId, collapsed) =>
    set((s) => ({ briefCollapsedByTopic: { ...s.briefCollapsedByTopic, [topicId]: collapsed } })),
  setMobilePane: (topicId, pane) =>
    set((s) => ({ mobilePaneByTopic: { ...s.mobilePaneByTopic, [topicId]: pane } })),
  setEventFeedPrefs: (topicId, patch) =>
    set((s) => ({
      eventFeedPrefsByTopic: {
        ...s.eventFeedPrefsByTopic,
        [topicId]: { ...(s.eventFeedPrefsByTopic[topicId] ?? defaultEventFeedPrefs()), ...patch },
      },
    })),
  setResearchPlanDraft: (topicId, prompt) =>
    set((s) => ({
      researchPlanDraftByTopic: {
        ...s.researchPlanDraftByTopic,
        [topicId]: prompt,
      },
    })),

  ensureLiveSummaryPoll: (topicId: number) => {
    if (liveSummaryPollers.has(topicId)) return;

    const tick = async () => {
      try {
        const prevGenerating = get().liveSummaryByTopic[topicId]?.isGenerating ?? false;
        const [st, data] = await Promise.all([
          fetchLiveSummaryStatus(topicId),
          fetchCachedSummary(topicId),
        ]);
        const content = data.content ?? "";
        const generatedAt = data.generated_at ?? null;
        const citations = data.citations ?? [];
        set((s) => ({
          liveSummaryByTopic: {
            ...s.liveSummaryByTopic,
            [topicId]: {
              content,
              generatedAt,
              citations,
              isGenerating: st.generating,
              lastStatus: st.status,
              lastError: st.error ?? null,
            },
          },
        }));
        if (prevGenerating && !st.generating) {
          get().endAction(
            `task:live-summary:${topicId}`,
            st.status === "error" ? "error" : "success",
            st.error ?? null,
            st.result_summary ?? null,
          );
          notifyTaskOutcome(
            `live-${topicId}`,
            st.status,
            st.error,
            st.result_summary,
            get().addToast,
          );
        }
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
              citations: s.liveSummaryByTopic[topicId]?.citations ?? [],
              isGenerating: false,
              lastStatus: "error",
              lastError: "Failed to poll AI analysis status",
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
      const citations = data.citations ?? [];
      set((s) => ({
        liveSummaryByTopic: {
          ...s.liveSummaryByTopic,
          [topicId]: {
            content,
            generatedAt,
            citations,
            isGenerating: st.generating,
            lastStatus: st.status,
            lastError: st.error ?? null,
          },
        },
      }));
      if (st.generating) {
        const current = get().getActionState(`task:live-summary:${topicId}`);
        if (current.status !== "running") get().beginAction(`task:live-summary:${topicId}`);
      } else {
        get().endAction(
          `task:live-summary:${topicId}`,
          st.status === "error" ? "error" : "success",
          st.error ?? null,
          st.result_summary ?? null,
        );
      }
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

    get().beginAction(`task:live-summary:${topicId}`);
    set((s) => ({
      liveSummaryByTopic: {
        ...s.liveSummaryByTopic,
        [topicId]: {
          content: s.liveSummaryByTopic[topicId]?.content ?? "",
          generatedAt: s.liveSummaryByTopic[topicId]?.generatedAt ?? null,
          citations: s.liveSummaryByTopic[topicId]?.citations ?? [],
          isGenerating: true,
          lastStatus: "running",
          lastError: null,
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
      get().endAction(`task:live-summary:${topicId}`, "error", "Failed to start AI analysis generation");
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

  ensureResearchPlanPoll: (topicId: number) => {
    if (researchPlanPollers.has(topicId)) return;

    const tick = async () => {
      try {
        const prevGenerating = get().researchPlanByTopic[topicId]?.isGenerating ?? false;
        const st = await fetchResearchPlanStatus(topicId);
        set((s) => ({
          researchPlanByTopic: {
            ...s.researchPlanByTopic,
            [topicId]: {
              isGenerating: st.generating,
              lastStatus: st.status,
              lastError: st.error ?? null,
              finishedAt: st.finished_at ?? null,
            },
          },
        }));
        if (prevGenerating && !st.generating) {
          get().endAction(
            `task:research-plan:${topicId}`,
            st.status === "error" ? "error" : "success",
            st.error ?? null,
            st.result_summary ?? null,
          );
          notifyTaskOutcome(
            `research-plan-${topicId}`,
            st.status,
            st.error,
            st.result_summary,
            get().addToast,
          );
        }
        if (!st.generating) {
          stopResearchPlanPoll(topicId);
        }
      } catch {
        stopResearchPlanPoll(topicId);
        set((s) => ({
          researchPlanByTopic: {
            ...s.researchPlanByTopic,
            [topicId]: {
              isGenerating: false,
              lastStatus: "error",
              lastError: "Failed to poll AI research setup status",
              finishedAt: s.researchPlanByTopic[topicId]?.finishedAt ?? null,
            },
          },
        }));
      }
    };

    void tick();
    const intervalId = setInterval(() => void tick(), 2000);
    researchPlanPollers.set(topicId, intervalId);
  },

  hydrateResearchPlanStatus: async (topicId: number) => {
    try {
      const st = await fetchResearchPlanStatus(topicId);
      set((s) => ({
        researchPlanByTopic: {
          ...s.researchPlanByTopic,
          [topicId]: {
            isGenerating: st.generating,
            lastStatus: st.status,
            lastError: st.error ?? null,
            finishedAt: st.finished_at ?? null,
          },
        },
      }));
      if (st.generating) {
        const current = get().getActionState(`task:research-plan:${topicId}`);
        if (current.status !== "running") get().beginAction(`task:research-plan:${topicId}`);
        get().ensureResearchPlanPoll(topicId);
      } else {
        get().endAction(
          `task:research-plan:${topicId}`,
          st.status === "error" ? "error" : "success",
          st.error ?? null,
          st.result_summary ?? null,
        );
      }
    } catch (e) {
      if (e instanceof Error && e.name !== "AbortError") {
        get().addToast("Failed to load AI research setup status", "warn");
      }
    }
  },

  startResearchPlanGeneration: async (topicId: number, prompt: string) => {
    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt) return;
    const current = get().researchPlanByTopic[topicId];
    if (current?.isGenerating) {
      get().ensureResearchPlanPoll(topicId);
      return;
    }

    get().beginAction(`task:research-plan:${topicId}`);
    set((s) => ({
      researchPlanDraftByTopic: {
        ...s.researchPlanDraftByTopic,
        [topicId]: trimmedPrompt,
      },
      researchPlanByTopic: {
        ...s.researchPlanByTopic,
        [topicId]: {
          isGenerating: true,
          lastStatus: "running",
          lastError: null,
          finishedAt: null,
        },
      },
    }));

    try {
      const resp = await postGenerateResearchPlan(topicId, trimmedPrompt);
      if (resp?.already_running || resp?.started) {
        get().ensureResearchPlanPoll(topicId);
        return;
      }
    } catch {
      get().endAction(`task:research-plan:${topicId}`, "error", "Failed to start AI research setup");
      set((s) => ({
        researchPlanByTopic: {
          ...s.researchPlanByTopic,
          [topicId]: {
            ...s.researchPlanByTopic[topicId],
            isGenerating: false,
            lastStatus: "error",
            lastError: "Failed to start AI research setup",
          },
        },
      }));
      return;
    }

    get().ensureResearchPlanPoll(topicId);
  },

  ensureGlobalOverviewPoll: (topicId: number) => {
    if (globalOverviewPollers.has(topicId)) return;

    const tick = async () => {
      try {
        const prevGenerating = get().globalOverviewByTopic[topicId]?.isGenerating ?? false;
        const [st, data] = await Promise.all([
          fetchGlobalOverviewStatus(topicId),
          fetchGlobalOverview(topicId),
        ]);
        const content = data.content ?? "";
        const citations = (data.citations ?? []) as AnalysisCitation[];
        set((s) => ({
          globalOverviewByTopic: {
            ...s.globalOverviewByTopic,
            [topicId]: {
              content,
              citations,
              isGenerating: st.generating,
              lastStatus: st.status,
              lastError: st.error ?? null,
            },
          },
        }));
        if (prevGenerating && !st.generating) {
          get().endAction(
            `task:global-overview:${topicId}`,
            st.status === "error" ? "error" : "success",
            st.error ?? null,
            st.result_summary ?? null,
          );
          notifyTaskOutcome(
            `global-${topicId}`,
            st.status,
            st.error,
            st.result_summary,
            get().addToast,
          );
        }
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
              lastStatus: "error",
              lastError: "Failed to poll global overview status",
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
      const citations = (data.citations ?? []) as AnalysisCitation[];
      set((s) => ({
        globalOverviewByTopic: {
          ...s.globalOverviewByTopic,
          [topicId]: {
            content,
            citations,
            isGenerating: st.generating,
            lastStatus: st.status,
            lastError: st.error ?? null,
          },
        },
      }));
      if (st.generating) {
        const current = get().getActionState(`task:global-overview:${topicId}`);
        if (current.status !== "running") get().beginAction(`task:global-overview:${topicId}`);
      } else {
        get().endAction(
          `task:global-overview:${topicId}`,
          st.status === "error" ? "error" : "success",
          st.error ?? null,
          st.result_summary ?? null,
        );
      }
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

    get().beginAction(`task:global-overview:${topicId}`);
    set((s) => ({
      globalOverviewByTopic: {
        ...s.globalOverviewByTopic,
        [topicId]: {
          content: s.globalOverviewByTopic[topicId]?.content ?? "",
          isGenerating: true,
          lastStatus: "running",
          lastError: null,
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
      get().endAction(`task:global-overview:${topicId}`, "error", "Failed to start global overview generation");
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
      const st = await fetchFetchStatus(topicId);
      const { running } = st;
      if (!running) {
        // Clear stale fetchingTopicId if it was pointing to this topic
        set((s) => s.fetchingTopicId === topicId ? { fetchingTopicId: null } : {});
        get().endAction(
          `task:fetch:${topicId ?? "all"}`,
          st.status === "error" ? "error" : "success",
          st.error ?? null,
          st.result_summary ?? null,
        );
        notifyTaskOutcome(
          `fetch-${topicId}`,
          st.status,
          st.error,
          st.result_summary,
          get().addToast,
        );
        return;
      }

      // Backend fetch is still running — restore fetchingTopicId and start polling
      set({ fetchingTopicId: topicId });
      get().beginAction(`task:fetch:${topicId ?? "all"}`);

      const tick = async () => {
        try {
          const st = await fetchFetchStatus(topicId);
          if (!st.running) {
            stopFetchPoll(key);
            get().endAction(
              `task:fetch:${topicId ?? "all"}`,
              st.status === "error" ? "error" : "success",
              st.error ?? null,
              st.result_summary ?? null,
            );
            notifyTaskOutcome(
              `fetch-${topicId}`,
              st.status,
              st.error,
              st.result_summary,
              get().addToast,
            );
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
      stopResearchPlanPoll(prev);
      stopFetchPoll(String(prev));
      stopChatTaskPoll(prev);
    }
    const nextTask = get().chatTaskByTopic[chatTopicKey(id)] ?? null;
    set({
      activeTopicId: id,
      highlightedEventId: null,
      selectedKnowledgeEventId: null,
      selectedKnowledgeEventTitle: null,
      isChatLoading: !!nextTask?.running,
    });
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
  setChatOpen: (v) =>
    set((s) => {
      if (s.activeTopicId == null) return { chatOpen: v };
      const currentPane = s.mobilePaneByTopic[s.activeTopicId] ?? "feed";
      return {
        chatOpen: v,
        mobilePaneByTopic: {
          ...s.mobilePaneByTopic,
          [s.activeTopicId]: v ? "chat" : currentPane === "chat" ? "analysis" : currentPane,
        },
      };
    }),
  setHighlightedEventId: (id) => set({ highlightedEventId: id }),
  refreshInsights: () => set((s) => ({ insightRefreshKey: s.insightRefreshKey + 1 })),
  clearChat: () =>
    set((s) => {
      const key = chatTopicKey(s.activeTopicId);
      stopChatTaskPoll(s.activeTopicId);
      return {
        chatConversationIdByTopic: { ...s.chatConversationIdByTopic, [key]: null },
        chatTaskByTopic: { ...s.chatTaskByTopic, [key]: null },
        selectedArticle: null,
        selectedEventContext: null,
        isChatLoading: false,
      };
    }),
  applyChatConversationPayload: (topicId, payload) =>
    set((s) => {
      const topicKey = chatTopicKey(topicId);
      const conversationId = payload?.conversation?.id ?? null;
      const nextConversationIdByTopic = {
        ...s.chatConversationIdByTopic,
        [topicKey]: conversationId,
      };
      const nextTaskByTopic = {
        ...s.chatTaskByTopic,
        [topicKey]: toTopicChatTask(payload?.task ?? null),
      };
      const nextMessagesByConversation = { ...s.chatMessagesByConversation };
      if (conversationId != null) {
        nextMessagesByConversation[String(conversationId)] = payload?.messages ?? [];
      }
      return {
        chatConversationIdByTopic: nextConversationIdByTopic,
        chatTaskByTopic: nextTaskByTopic,
        chatMessagesByConversation: nextMessagesByConversation,
        isChatLoading: s.activeTopicId === topicId ? !!payload?.task?.running : s.isChatLoading,
      };
    }),
  hydrateChatConversation: async (topicId) => {
    const topicKey = chatTopicKey(topicId);
    const knownConversationId = get().chatConversationIdByTopic[topicKey] ?? null;
    let payload: ChatConversationPayload | null = null;

    if (knownConversationId != null) {
      payload = await fetchChatConversation(knownConversationId);
    }
    if (!payload && topicId != null) {
      payload = await fetchLatestChatConversationForTopic(topicId);
    }

    get().applyChatConversationPayload(topicId, payload);
    if (payload?.task?.running) get().ensureChatTaskPoll(topicId);
    else stopChatTaskPoll(topicId);
  },
  startChatTask: async (message, articleContext) => {
    const topicId = get().activeTopicId;
    const topicKey = chatTopicKey(topicId);
    const conversationId = get().chatConversationIdByTopic[topicKey] ?? null;
    await apiCreateChatTask(message, articleContext, topicId, conversationId);
    await get().hydrateChatConversation(topicId);
    get().ensureChatTaskPoll(topicId);
    set({
      selectedArticle: null,
      selectedEventContext: null,
      isChatLoading: true,
    });
  },
  ensureChatTaskPoll: (topicId) => {
    if (topicId == null) return;
    const topicKey = chatTopicKey(topicId);
    const task = get().chatTaskByTopic[topicKey];
    if (!task?.running || !task.taskId) {
      stopChatTaskPoll(topicId);
      return;
    }
    if (chatTaskPollers.has(topicKey)) return;

    const tick = async () => {
      const currentTask = get().chatTaskByTopic[topicKey];
      if (!currentTask?.taskId) {
        stopChatTaskPoll(topicId);
        return;
      }
      try {
        const latest = await fetchChatTaskStatus(currentTask.taskId);
        if (!latest) {
          stopChatTaskPoll(topicId);
          await get().hydrateChatConversation(topicId);
          return;
        }
        set((s) => ({
          chatTaskByTopic: {
            ...s.chatTaskByTopic,
            [topicKey]: toTopicChatTask(latest),
          },
          isChatLoading: s.activeTopicId === topicId ? latest.running : s.isChatLoading,
        }));
        if (!latest.running) {
          stopChatTaskPoll(topicId);
          await get().hydrateChatConversation(topicId);
        }
      } catch {}
    };

    void tick();
    const intervalId = setInterval(() => void tick(), 2000);
    chatTaskPollers.set(topicKey, intervalId);
  },
  applyChatStreamEvent: (conversationId, event) =>
    set((s) => {
      const conversationKey = String(conversationId);
      const messages = [...(s.chatMessagesByConversation[conversationKey] ?? [])];
      const idx = messages.findIndex((msg) => msg.id === event.assistant_message_id);
      if (idx === -1) return {};

      const current = messages[idx];
      const updated: ChatMessage = {
        ...current,
        content: event.content ? `${current.content}${event.content}` : current.content,
        status: event.message_status ?? current.status,
        sources: event.sources ?? current.sources,
        trace: event.trace ? replaceTrace(current.trace, event.trace) : current.trace,
        error: event.error !== undefined ? event.error : current.error,
      };
      if (event.status && (updated.trace?.length ?? 0) === 0) {
        updated.status = "running";
      }
      messages[idx] = updated;

      const nextTaskByTopic = { ...s.chatTaskByTopic };
      let nextIsChatLoading = s.isChatLoading;
      for (const [topicKey, mappedConversationId] of Object.entries(s.chatConversationIdByTopic)) {
        if (mappedConversationId !== conversationId) continue;
        const currentTask = nextTaskByTopic[topicKey];
        if (currentTask && event.task_status) {
          nextTaskByTopic[topicKey] = {
            ...currentTask,
            status: event.task_status,
            running: event.task_status === "running",
            error: event.error !== undefined ? event.error : currentTask.error,
            finishedAt:
              event.task_status === "done" || event.task_status === "error"
                ? new Date().toISOString()
                : currentTask.finishedAt,
          };
        }
        if (topicKey === chatTopicKey(s.activeTopicId) && event.done) {
          nextIsChatLoading = false;
        }
      }

      return {
        chatMessagesByConversation: {
          ...s.chatMessagesByConversation,
          [conversationKey]: messages,
        },
        chatTaskByTopic: nextTaskByTopic,
        isChatLoading: nextIsChatLoading,
      };
    }),
    }),
    {
      name: "domain-monitor-chat",
      partialize: (state) => ({
        chatConversationIdByTopic: state.chatConversationIdByTopic,
        chatMessagesByConversation: state.chatMessagesByConversation,
        analysisTabByTopic: state.analysisTabByTopic,
        analysisWindowByTopic: state.analysisWindowByTopic,
        briefCollapsedByTopic: state.briefCollapsedByTopic,
        mobilePaneByTopic: state.mobilePaneByTopic,
        eventFeedPrefsByTopic: state.eventFeedPrefsByTopic,
        researchPlanDraftByTopic: state.researchPlanDraftByTopic,
        // Reset transient states on hydration: "running" tasks never completed (process
        // was killed) and "error" states from a previous session reflect stale backend
        // errors (e.g. ChromaDB crash) that may no longer be valid.
        actionStates: Object.fromEntries(
          Object.entries(state.actionStates).map(([k, v]) => [
            k,
            v.status === "running" || v.status === "error"
              ? { ...v, status: "idle" as const, error: null }
              : v,
          ])
        ),
      }),
    }
  )
);
