"use client";

import { useEffect, useState, useMemo } from "react";
import {
  Loader2,
  Inbox,
  LayoutList,
  Layers,
  TrendingUp,
  TrendingDown,
  Minus,
  CircleDot,
  ArrowDownWideNarrow,
  Clock,
  Archive,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { useStore } from "@/stores/useStore";
import { fetchArticles, fetchEvents, createSSEConnection } from "@/lib/api";
import EventCard from "./EventCard";
import NewsCard from "./NewsCard";
import type { Article } from "@/lib/api";

type ViewMode = "events" | "all";
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
    highlightedEventId,
    refreshInsights,
    insightRefreshKey,
  } = useStore();

  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<ViewMode>("events");
  const [sentimentFilter, setSentimentFilter] = useState<SentimentFilter>("all");
  const [sortMode, setSortMode] = useState<SortMode>("relevance");
  const [events, setEvents] = useState<Article[]>([]);
  const [newIds, setNewIds] = useState<Set<string>>(new Set());

  // Archived fold
  const [archivedItems, setArchivedItems] = useState<Article[]>([]);
  const [archivedCount, setArchivedCount] = useState(0);
  const [showArchived, setShowArchived] = useState(false);

  // Fetch active articles
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    if (viewMode === "events") {
      fetchEvents(activeTopicId, 50, 0, sortMode, "active")
        .then((data) => { if (!cancelled) setEvents(data.events); })
        .catch((e) => { if (process.env.NODE_ENV === "development") console.warn("[fetch]", e); })
        .finally(() => { if (!cancelled) setLoading(false); });
    } else {
      fetchArticles(50, 0, activeTopicId, sortMode, "active")
        .then((data) => { if (!cancelled) setArticles(data.articles); })
        .catch((e) => { if (process.env.NODE_ENV === "development") console.warn("[fetch]", e); })
        .finally(() => { if (!cancelled) setLoading(false); });
    }
    return () => { cancelled = true; };
  }, [activeTopicId, viewMode, sortMode, setArticles, insightRefreshKey]);

  // Fetch archived count
  useEffect(() => {
    let cancelled = false;
    const fetcher = viewMode === "events" ? fetchEvents : fetchArticles;
    if (viewMode === "events") {
      fetchEvents(activeTopicId, 1, 0, sortMode, "archived")
        .then((data) => { if (!cancelled) setArchivedCount(data.total); })
        .catch(() => {});
    } else {
      fetchArticles(1, 0, activeTopicId, sortMode, "archived")
        .then((data) => { if (!cancelled) setArchivedCount(data.total); })
        .catch(() => {});
    }
    return () => { cancelled = true; };
  }, [activeTopicId, viewMode, sortMode, insightRefreshKey]);

  // Load archived items when expanded
  useEffect(() => {
    if (!showArchived) return;
    let cancelled = false;
    if (viewMode === "events") {
      fetchEvents(activeTopicId, 50, 0, sortMode, "archived")
        .then((data) => { if (!cancelled) setArchivedItems(data.events); })
        .catch(() => {});
    } else {
      fetchArticles(50, 0, activeTopicId, sortMode, "archived")
        .then((data) => { if (!cancelled) setArchivedItems(data.articles); })
        .catch(() => {});
    }
    return () => { cancelled = true; };
  }, [showArchived, activeTopicId, viewMode, sortMode, insightRefreshKey]);

  useEffect(() => {
    let alive = true;
    const sse = createSSEConnection((incoming) => {
      if (!alive) return;
      const filtered =
        activeTopicId != null
          ? incoming.filter((a) => a.topic_id === activeTopicId)
          : incoming;
      if (filtered.length === 0) return;
      const ids = filtered.map((a) => a.id);
      setNewIds((prev) => { const next = new Set(prev); ids.forEach((id) => next.add(id)); return next; });
      prependArticles(filtered);

      if (viewMode === "events") {
        const canonicals = filtered.filter((a) => a.is_canonical === 1);
        if (canonicals.length > 0) {
          setEvents((prev) => {
            const existingIds = new Set(prev.map((e) => e.id));
            const unique = canonicals.filter((c) => !existingIds.has(c.id));
            return [...unique, ...prev];
          });
        }
      }
      refreshInsights();

      setTimeout(() => {
        if (!alive) return;
        setNewIds((prev) => { const next = new Set(prev); ids.forEach((id) => next.delete(id)); return next; });
      }, 10000);
    });
    return () => { alive = false; sse.close(); };
  }, [activeTopicId, prependArticles, viewMode, refreshInsights]);

  function handleRemoved(id: string) {
    setEvents((prev) => prev.filter((e) => e.id !== id));
    setArticles(articles.filter((a) => a.id !== id));
    setArchivedItems((prev) => prev.filter((a) => a.id !== id));
    setArchivedCount((c) => Math.max(0, c - 1));
    refreshInsights();
  }

  function handleArchived(id: string) {
    setEvents((prev) => prev.filter((e) => e.id !== id));
    setArticles(articles.filter((a) => a.id !== id));
    setArchivedCount((c) => c + 1);
    refreshInsights();
  }

  function handleRestored(id: string) {
    setArchivedItems((prev) => prev.filter((a) => a.id !== id));
    setArchivedCount((c) => Math.max(0, c - 1));
    refreshInsights();
  }

  const rawItems = viewMode === "events" ? events : articles;

  const filteredItems = useMemo(() => {
    if (sentimentFilter === "all") return rawItems;
    return rawItems.filter((item) => item.sentiment === sentimentFilter);
  }, [rawItems, sentimentFilter]);

  const sentimentCounts = useMemo(() => {
    const counts = { all: rawItems.length, positive: 0, neutral: 0, negative: 0 };
    for (const item of rawItems) {
      const s = item.sentiment as SentimentFilter;
      if (s in counts) counts[s]++;
    }
    return counts;
  }, [rawItems]);

  if (loading) {
    return (
      <div className="flex-3 min-w-[260px] flex items-center justify-center border-r border-border">
        <Loader2 className="w-6 h-6 text-accent animate-spin" />
      </div>
    );
  }

  if (rawItems.length === 0 && archivedCount === 0) {
    return (
      <div className="flex-3 min-w-[260px] flex flex-col items-center justify-center text-muted gap-3 border-r border-border">
        <Inbox className="w-12 h-12" />
        <p className="text-sm">No articles yet.</p>
        <p className="text-xs">
          Add keywords and click &quot;Fetch Now&quot; to get started.
        </p>
      </div>
    );
  }

  return (
    <div className="flex-3 min-w-[260px] flex flex-col overflow-hidden border-r border-border">
      {/* Toolbar */}
      <div className="px-4 py-2 border-b border-border space-y-2">
        {/* View mode */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setViewMode("events")}
            className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${
              viewMode === "events"
                ? "bg-accent/15 text-accent"
                : "text-muted hover:text-foreground hover:bg-surface-hover"
            }`}
          >
            <Layers className="w-3 h-3" />
            Events
          </button>
          <button
            onClick={() => setViewMode("all")}
            className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${
              viewMode === "all"
                ? "bg-accent/15 text-accent"
                : "text-muted hover:text-foreground hover:bg-surface-hover"
            }`}
          >
            <LayoutList className="w-3 h-3" />
            All Articles
          </button>
          {/* Sort toggle */}
          <div className="ml-auto flex items-center gap-1">
            <button
              onClick={() => setSortMode("relevance")}
              className={`inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium transition-colors ${
                sortMode === "relevance"
                  ? "bg-important/15 text-important"
                  : "text-muted hover:text-foreground hover:bg-surface-hover"
              }`}
              title="Sort by importance"
            >
              <ArrowDownWideNarrow className="w-3 h-3" />
              Relevance
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
        {filteredItems.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-muted">
            <p className="text-xs">No {sentimentFilter} {viewMode === "events" ? "events" : "articles"} found.</p>
          </div>
        ) : (
          <>
            {filteredItems.map((item) =>
              viewMode === "events" ? (
                <EventCard
                  key={item.id}
                  article={item}
                  isNew={newIds.has(item.id)}
                  isHighlighted={highlightedEventId === (item.event_id || item.id)}
                  onRemoved={handleRemoved}
                  onArchived={handleArchived}
                />
              ) : (
                <NewsCard
                  key={item.id}
                  article={item}
                  isNew={newIds.has(item.id)}
                  onRemoved={handleRemoved}
                  onArchived={handleArchived}
                />
              )
            )}
          </>
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
                {archivedItems.map((item) =>
                  viewMode === "events" ? (
                    <EventCard
                      key={item.id}
                      article={item}
                      onRemoved={handleRemoved}
                      onRestored={handleRestored}
                    />
                  ) : (
                    <NewsCard
                      key={item.id}
                      article={item}
                      onRemoved={handleRemoved}
                      onRestored={handleRestored}
                    />
                  )
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
