"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Loader2,
  Inbox,
  LayoutList,
  TrendingUp,
  TrendingDown,
  Minus,
  CircleDot,
  ArrowDownWideNarrow,
  Clock,
  Archive,
  ChevronDown,
  ChevronUp,
  Filter,
  X,
  Wifi,
  WifiOff,
} from "lucide-react";
import { useStore } from "@/stores/useStore";
import { fetchArticles, createSSEConnection } from "@/lib/api";
import NewsCard from "./NewsCard";
import type { Article } from "@/lib/api";

type SentimentFilter = "all" | "positive" | "neutral" | "negative";
type SortMode = "relevance" | "latest";
const PAGE_SIZE = 50;

const SENTIMENT_FILTERS: {
  key: SentimentFilter;
  label: string;
  icon: React.ElementType;
  color: string;
  activeColor: string;
}[] = [
  { key: "all", label: "All", icon: CircleDot, color: "text-muted", activeColor: "bg-accent/15 text-accent" },
  { key: "positive", label: "Positive", icon: TrendingUp, color: "text-positive", activeColor: "bg-positive/15 text-positive" },
  { key: "neutral", label: "Neutral", icon: Minus, color: "text-muted", activeColor: "bg-muted/15 text-foreground" },
  { key: "negative", label: "Negative", icon: TrendingDown, color: "text-negative", activeColor: "bg-negative/15 text-negative" },
];

export default function EventFeed({
  layout = "desktop",
}: {
  layout?: "desktop" | "mobile";
}) {
  const {
    articles,
    setArticles,
    prependArticles,
    activeTopicId,
    refreshInsights,
    selectedKnowledgeEventId,
    selectedKnowledgeEventTitle,
    setSelectedKnowledgeEvent,
    eventFeedPrefsByTopic,
    setEventFeedPrefs,
  } = useStore();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [activeTotal, setActiveTotal] = useState(0);
  const [loadedActiveCount, setLoadedActiveCount] = useState(0);
  const topicPrefs = activeTopicId != null
    ? eventFeedPrefsByTopic[activeTopicId]
    : undefined;
  const sentimentFilter = (topicPrefs?.sentimentFilter ?? "all") as SentimentFilter;
  const sortMode = (topicPrefs?.sortMode ?? "relevance") as SortMode;

  const [newArticleIds, setNewArticleIds] = useState<Set<string>>(new Set());
  const [sseState, setSseState] = useState<"connecting" | "open" | "reconnecting" | "closed">("connecting");

  // Archived fold
  const [archivedArticles, setArchivedArticles] = useState<Article[]>([]);
  const [archivedCount, setArchivedCount] = useState(0);
  const showArchived = topicPrefs?.showArchived ?? false;
  const isMobile = layout === "mobile";
  const feedScrollRef = useRef<HTMLDivElement | null>(null);
  const loadMoreRef = useRef<HTMLDivElement | null>(null);
  const shellClass = isMobile
    ? "flex h-full min-h-0 w-full flex-col overflow-hidden bg-surface"
    : "flex-3 min-w-[260px] flex flex-col overflow-hidden border-r border-border";
  const hasMoreActive = loadedActiveCount < activeTotal;

  // Fetch active articles — re-fetch when event filter changes
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setLoadMoreError(null);
    setLoadingMore(false);
    setActiveTotal(0);
    setLoadedActiveCount(0);

    fetchArticles(PAGE_SIZE, 0, activeTopicId, sortMode, "active", selectedKnowledgeEventId)
      .then((data) => {
        if (!cancelled) {
          setArticles(data.articles);
          setActiveTotal(data.total);
          setLoadedActiveCount(data.articles.length);
        }
      })
      .catch((e) => {
        if (process.env.NODE_ENV === "development") console.warn("[fetch articles]", e);
        if (!cancelled) setError("Failed to load articles. Please retry.");
      })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [activeTopicId, sortMode, reloadKey, selectedKnowledgeEventId, setArticles]);

  const loadMoreArticles = useCallback(async () => {
    if (loading || loadingMore || !hasMoreActive) return;

    const offset = loadedActiveCount;
    setLoadingMore(true);
    setLoadMoreError(null);

    try {
      const data = await fetchArticles(
        PAGE_SIZE,
        offset,
        activeTopicId,
        sortMode,
        "active",
        selectedKnowledgeEventId,
      );
      const latestArticles = useStore.getState().articles;
      const existingIds = new Set(latestArticles.map((article) => article.id));
      const uniqueArticles = data.articles.filter((article) => !existingIds.has(article.id));
      const nextLoadedCount = data.articles.length === 0 ? data.total : offset + data.articles.length;

      setActiveTotal(data.total);
      setLoadedActiveCount(Math.min(nextLoadedCount, data.total));

      if (uniqueArticles.length > 0) {
        setArticles([...latestArticles, ...uniqueArticles]);
      }
    } catch (e) {
      if (process.env.NODE_ENV === "development") console.warn("[load more articles]", e);
      setLoadMoreError("Failed to load more articles.");
    } finally {
      setLoadingMore(false);
    }
  }, [
    activeTopicId,
    hasMoreActive,
    loadedActiveCount,
    loading,
    loadingMore,
    selectedKnowledgeEventId,
    setArticles,
    sortMode,
  ]);

  useEffect(() => {
    if (loading || loadingMore || !hasMoreActive) return;

    const root = feedScrollRef.current;
    const target = loadMoreRef.current;
    if (!root || !target) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          void loadMoreArticles();
        }
      },
      {
        root,
        rootMargin: "160px 0px",
        threshold: 0.1,
      },
    );

    observer.observe(target);
    return () => observer.disconnect();
  }, [hasMoreActive, loadMoreArticles, loading, loadingMore]);

  // Fetch archived count
  useEffect(() => {
    let cancelled = false;
    fetchArticles(1, 0, activeTopicId, sortMode, "archived", selectedKnowledgeEventId)
      .then((data) => { if (!cancelled) setArchivedCount(data.total); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [activeTopicId, sortMode, selectedKnowledgeEventId]);

  // Load archived items when expanded
  useEffect(() => {
    if (!showArchived) return;
    let cancelled = false;
    fetchArticles(50, 0, activeTopicId, sortMode, "archived", selectedKnowledgeEventId)
      .then((data) => { if (!cancelled) setArchivedArticles(data.articles); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [showArchived, activeTopicId, sortMode, selectedKnowledgeEventId]);

  // SSE: structured delta → update articles store + signal new events for evolution
  useEffect(() => {
    // Don't prepend SSE articles when viewing a filtered event — avoids stale data appearing
    if (selectedKnowledgeEventId) {
      setSseState("closed");
      return;
    }

    let alive = true;
    const sse = createSSEConnection(
      (delta) => {
        if (!alive) return;

        const { articles: incoming } = delta;

        const filtered =
          activeTopicId != null
            ? incoming.filter((a) => a.topic_id === activeTopicId)
            : incoming;

        if (filtered.length > 0) {
          const articleIds = filtered.map((a) => a.id);
          setNewArticleIds((prev) => {
            const next = new Set(prev);
            articleIds.forEach((id) => next.add(id));
            return next;
          });
          prependArticles(filtered);
          setTimeout(() => {
            if (!alive) return;
            setNewArticleIds((prev) => {
              const next = new Set(prev);
              articleIds.forEach((id) => next.delete(id));
              return next;
            });
          }, 10_000);
        }

        refreshInsights();
      },
      (state) => {
        if (!alive) return;
        setSseState(state);
      },
    );
    return () => {
      alive = false;
      sse.close();
    };
  }, [activeTopicId, prependArticles, refreshInsights, selectedKnowledgeEventId]);

  function handleArticleRemoved(id: string) {
    const wasActive = articles.some((article) => article.id === id);
    const wasArchived = archivedArticles.some((article) => article.id === id);

    setArticles(articles.filter((a) => a.id !== id));
    setArchivedArticles((prev) => prev.filter((a) => a.id !== id));
    if (wasActive) {
      setLoadedActiveCount((count) => Math.max(0, count - 1));
      setActiveTotal((count) => Math.max(0, count - 1));
    }
    if (wasArchived) {
      setArchivedCount((count) => Math.max(0, count - 1));
    }
    refreshInsights();
  }

  function handleArticleArchived(id: string) {
    setArticles(articles.filter((a) => a.id !== id));
    setLoadedActiveCount((count) => Math.max(0, count - 1));
    setActiveTotal((count) => Math.max(0, count - 1));
    setArchivedCount((c) => c + 1);
    refreshInsights();
  }

  function handleArticleRestored(id: string) {
    setArchivedArticles((prev) => prev.filter((a) => a.id !== id));
    setActiveTotal((count) => count + 1);
    setArchivedCount((c) => Math.max(0, c - 1));
    refreshInsights();
  }

  // ── Filtering / counting ────────────────────────────────────────────────────

  const filteredArticles = useMemo(() => {
    if (sentimentFilter === "all") return articles;
    return articles.filter((a) => a.sentiment === sentimentFilter);
  }, [articles, sentimentFilter]);

  const sentimentCounts = useMemo(() => {
    const counts = { all: articles.length, positive: 0, neutral: 0, negative: 0 };
    for (const item of articles) {
      const s = item.sentiment as SentimentFilter;
      if (s in counts) counts[s]++;
    }
    return counts;
  }, [articles]);

  // ── Render states ───────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className={`${shellClass} items-center justify-center`}>
        <Loader2 className="w-6 h-6 text-accent animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className={`${shellClass} items-center justify-center gap-3 px-6 text-center`}>
        <AlertTriangle className="h-10 w-10 text-important" />
        <div>
          <p className="text-sm font-medium">News unavailable</p>
          <p className="mt-1 text-xs text-muted">{error}</p>
        </div>
        <button
          onClick={() => setReloadKey((v) => v + 1)}
          className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-accent-hover"
        >
          Retry
        </button>
      </div>
    );
  }

  if (articles.length === 0 && archivedCount === 0) {
    return (
      <div className={`${shellClass} items-center justify-center text-muted gap-3`}>
        <Inbox className="w-12 h-12" />
        {selectedKnowledgeEventId ? (
          <>
            <p className="text-sm">No articles found for this event.</p>
            <button
              onClick={() => setSelectedKnowledgeEvent(null)}
              className="text-xs text-accent hover:underline"
            >
              Clear filter
            </button>
          </>
        ) : (
          <>
            <p className="text-sm">No monitoring items yet.</p>
            <p className="text-xs text-center">
              Add keywords in Research Setup, then click &quot;Fetch Now&quot; to start building this topic workspace.
            </p>
          </>
        )}
      </div>
    );
  }

  return (
    <div className={shellClass}>
      {/* Event filter banner */}
      {selectedKnowledgeEventId && (
        <div className="px-4 py-2 bg-accent/8 border-b border-accent/20 flex items-center gap-2">
          <Filter className="w-3 h-3 text-accent shrink-0" />
          <span className="text-[11px] text-accent flex-1 line-clamp-1 font-medium">
            {selectedKnowledgeEventTitle ?? "Event filter active"}
          </span>
          <button
            onClick={() => setSelectedKnowledgeEvent(null)}
            className="text-accent/70 hover:text-accent transition-colors"
            title="Clear event filter"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {sseState !== "open" && !selectedKnowledgeEventId && (
        <div className="px-4 py-1.5 border-b border-border/80 bg-surface-hover/50 flex items-center gap-1.5 text-[11px] text-muted">
          {sseState === "reconnecting" ? (
            <WifiOff className="w-3 h-3 text-important" />
          ) : (
            <Wifi className="w-3 h-3" />
          )}
          <span>
            {sseState === "connecting"
              ? "Connecting live updates…"
              : "Live updates reconnecting…"}
          </span>
        </div>
      )}

      {/* Toolbar */}
      <div className="px-4 py-2 border-b border-border space-y-2">
        {/* View label + sort */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1 text-[11px] font-medium text-muted">
            <LayoutList className="w-3 h-3" />
            <span>News</span>
          </div>

          {/* Sort toggle */}
          <div className="ml-auto flex flex-wrap items-center gap-1">
            <button
              onClick={() => activeTopicId != null && setEventFeedPrefs(activeTopicId, { sortMode: "relevance" })}
              className={`inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium transition-colors ${
                sortMode === "relevance"
                  ? "bg-important/15 text-important"
                  : "text-muted hover:text-foreground hover:bg-surface-hover"
              }`}
              title="Sort by priority"
            >
              <ArrowDownWideNarrow className="w-3 h-3" />
              Priority
            </button>
            <button
              onClick={() => activeTopicId != null && setEventFeedPrefs(activeTopicId, { sortMode: "latest" })}
              className={`inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium transition-colors ${
                sortMode === "latest"
                  ? "bg-accent/15 text-accent"
                  : "text-muted hover:text-foreground hover:bg-surface-hover"
              }`}
              title="Sort by time"
            >
              <Clock className="w-3 h-3" />
              Latest
            </button>
          </div>
        </div>

        {/* Sentiment filter */}
        <div className="flex flex-wrap items-center gap-1">
          {SENTIMENT_FILTERS.map(({ key, label, icon: Icon, color, activeColor }) => {
            const count = sentimentCounts[key];
            const isActive = sentimentFilter === key;
            return (
              <button
                key={key}
                onClick={() => activeTopicId != null && setEventFeedPrefs(activeTopicId, { sentimentFilter: key })}
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium transition-colors ${
                  isActive ? activeColor : "text-muted hover:bg-surface-hover"
                }`}
              >
                <Icon className={`w-3 h-3 ${isActive ? "" : color}`} />
                {label}
                <span className={`text-[9px] ${isActive ? "opacity-80" : "opacity-50"}`}>
                  {count}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Feed */}
      <div ref={feedScrollRef} className="flex-1 overflow-y-auto p-3 sm:p-4 space-y-3">
        {filteredArticles.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-muted">
            <p className="text-xs">No {sentimentFilter !== "all" ? sentimentFilter : ""} articles found.</p>
          </div>
        ) : (
          filteredArticles.map((item) => (
            <NewsCard
              key={item.id}
              article={item}
              isNew={newArticleIds.has(item.id)}
              onRemoved={handleArticleRemoved}
              onArchived={handleArticleArchived}
            />
          ))
        )}

        <div ref={loadMoreRef} className="h-1" aria-hidden="true" />

        {loadingMore && (
          <div className="flex items-center justify-center gap-2 py-2 text-xs text-muted">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>Loading more news…</span>
          </div>
        )}

        {loadMoreError && (
          <div className="flex items-center justify-center gap-2 py-2 text-xs text-muted">
            <span>{loadMoreError}</span>
            <button
              onClick={() => void loadMoreArticles()}
              className="rounded-md border border-border px-2 py-1 text-[11px] font-medium text-foreground transition-colors hover:bg-surface-hover"
            >
              Retry
            </button>
          </div>
        )}

        {!loadingMore && !loadMoreError && !hasMoreActive && activeTotal > 0 && (
          <div className="flex items-center justify-center py-2 text-[11px] text-muted">
            All news loaded
          </div>
        )}

        {/* Archived fold */}
        {archivedCount > 0 && (
          <div className="mt-4">
            <button
              onClick={() => activeTopicId != null && setEventFeedPrefs(activeTopicId, { showArchived: !showArchived })}
              className="w-full flex items-center gap-2 py-2 text-[11px] text-muted hover:text-foreground transition-colors"
            >
              <div className="flex-1 border-t border-border/60" />
              <Archive className="w-3.5 h-3.5" />
              <span>{archivedCount} archived</span>
              {showArchived ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
              <div className="flex-1 border-t border-border/60" />
            </button>

            {showArchived && (
              <div className="space-y-3 mt-2">
                {archivedArticles.map((item) => (
                  <NewsCard
                    key={item.id}
                    article={item}
                    onRemoved={handleArticleRemoved}
                    onRestored={handleArticleRestored}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
