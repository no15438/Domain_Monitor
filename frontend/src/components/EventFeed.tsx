"use client";

import { useEffect, useState, useMemo } from "react";
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
} from "lucide-react";
import { useStore } from "@/stores/useStore";
import { fetchArticles, createSSEConnection } from "@/lib/api";
import NewsCard from "./NewsCard";
import type { Article } from "@/lib/api";

type SentimentFilter = "all" | "positive" | "neutral" | "negative";
type SortMode = "relevance" | "latest";

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

export default function EventFeed() {
  const {
    articles,
    setArticles,
    prependArticles,
    activeTopicId,
    refreshInsights,
    selectedKnowledgeEventId,
    selectedKnowledgeEventTitle,
    setSelectedKnowledgeEvent,
  } = useStore();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [sentimentFilter, setSentimentFilter] = useState<SentimentFilter>("all");
  const [sortMode, setSortMode] = useState<SortMode>("relevance");

  const [newArticleIds, setNewArticleIds] = useState<Set<string>>(new Set());

  // Archived fold
  const [archivedArticles, setArchivedArticles] = useState<Article[]>([]);
  const [archivedCount, setArchivedCount] = useState(0);
  const [showArchived, setShowArchived] = useState(false);

  // Fetch active articles — re-fetch when event filter changes
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchArticles(50, 0, activeTopicId, sortMode, "active", selectedKnowledgeEventId)
      .then((data) => { if (!cancelled) setArticles(data.articles); })
      .catch((e) => {
        if (process.env.NODE_ENV === "development") console.warn("[fetch articles]", e);
        if (!cancelled) setError("Failed to load articles. Please retry.");
      })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [activeTopicId, sortMode, reloadKey, selectedKnowledgeEventId, setArticles]);

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
    if (selectedKnowledgeEventId) return;

    let alive = true;
    const sse = createSSEConnection((delta) => {
      if (!alive) return;

      const { articles: incoming, new_event_ids } = delta;

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
    });
    return () => { alive = false; sse.close(); };
  }, [activeTopicId, prependArticles, refreshInsights, selectedKnowledgeEventId]);

  function handleArticleRemoved(id: string) {
    setArticles(articles.filter((a) => a.id !== id));
    setArchivedArticles((prev) => prev.filter((a) => a.id !== id));
    setArchivedCount((c) => Math.max(0, c - 1));
    refreshInsights();
  }

  function handleArticleArchived(id: string) {
    setArticles(articles.filter((a) => a.id !== id));
    setArchivedCount((c) => c + 1);
    refreshInsights();
  }

  function handleArticleRestored(id: string) {
    setArchivedArticles((prev) => prev.filter((a) => a.id !== id));
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
      <div className="flex-3 min-w-[260px] flex items-center justify-center border-r border-border">
        <Loader2 className="w-6 h-6 text-accent animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-3 min-w-[260px] flex flex-col items-center justify-center gap-3 border-r border-border px-6 text-center">
        <AlertTriangle className="h-10 w-10 text-important" />
        <div>
          <p className="text-sm font-medium">Activity feed unavailable</p>
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
      <div className="flex-3 min-w-[260px] flex flex-col items-center justify-center text-muted gap-3 border-r border-border">
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
    <div className="flex-3 min-w-[260px] flex flex-col overflow-hidden border-r border-border">
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

      {/* Toolbar */}
      <div className="px-4 py-2 border-b border-border space-y-2">
        {/* View label + sort */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 text-[11px] font-medium text-muted">
            <LayoutList className="w-3 h-3" />
            <span>News</span>
          </div>

          {/* Sort toggle */}
          <div className="ml-auto flex items-center gap-1">
            <button
              onClick={() => setSortMode("relevance")}
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
              onClick={() => setSortMode("latest")}
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
        <div className="flex items-center gap-1">
          {SENTIMENT_FILTERS.map(({ key, label, icon: Icon, color, activeColor }) => {
            const count = sentimentCounts[key];
            const isActive = sentimentFilter === key;
            return (
              <button
                key={key}
                onClick={() => setSentimentFilter(key)}
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
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
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

        {/* Archived fold */}
        {archivedCount > 0 && (
          <div className="mt-4">
            <button
              onClick={() => setShowArchived((v) => !v)}
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
