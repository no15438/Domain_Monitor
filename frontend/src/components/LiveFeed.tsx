"use client";

import { useEffect, useState } from "react";
import { Loader2, Inbox, Archive, ChevronDown, ChevronUp } from "lucide-react";
import { useStore } from "@/stores/useStore";
import { fetchArticles, createSSEConnection } from "@/lib/api";
import NewsCard from "./NewsCard";

export default function LiveFeed() {
  const { articles, setArticles, prependArticles, activeTopicId, refreshInsights } = useStore();
  const [loading, setLoading] = useState(true);
  const [newIds, setNewIds] = useState<Set<string>>(new Set());

  // Archived
  const [archivedItems, setArchivedItems] = useState<import("@/lib/api").Article[]>([]);
  const [archivedCount, setArchivedCount] = useState(0);
  const [showArchived, setShowArchived] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchArticles(50, 0, activeTopicId, "relevance", "active")
      .then((data) => { if (!cancelled) setArticles(data.articles); })
      .catch((e) => { if (process.env.NODE_ENV === "development") console.warn("[fetch]", e); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [activeTopicId, setArticles]);

  // Archived count
  useEffect(() => {
    let cancelled = false;
    fetchArticles(1, 0, activeTopicId, "relevance", "archived")
      .then((data) => { if (!cancelled) setArchivedCount(data.total); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [activeTopicId]);

  // Load archived when expanded
  useEffect(() => {
    if (!showArchived) return;
    let cancelled = false;
    fetchArticles(50, 0, activeTopicId, "relevance", "archived")
      .then((data) => { if (!cancelled) setArchivedItems(data.articles); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [showArchived, activeTopicId]);

  useEffect(() => {
    let alive = true;
    const sse = createSSEConnection(({ articles: incoming }) => {
      if (!alive) return;
      const filtered =
        activeTopicId != null
          ? incoming.filter((a) => a.topic_id === activeTopicId)
          : incoming;
      if (filtered.length === 0) return;
      const ids = filtered.map((a) => a.id);
      setNewIds((prev) => { const next = new Set(prev); ids.forEach((id) => next.add(id)); return next; });
      prependArticles(filtered);
      setTimeout(() => {
        if (!alive) return;
        setNewIds((prev) => { const next = new Set(prev); ids.forEach((id) => next.delete(id)); return next; });
      }, 10000);
    });
    return () => { alive = false; sse.close(); };
  }, [activeTopicId, prependArticles]);

  function handleRemoved(id: string) {
    setArticles(articles.filter((a) => a.id !== id));
    setArchivedItems((prev) => prev.filter((a) => a.id !== id));
    setArchivedCount((c) => Math.max(0, c - 1));
    refreshInsights();
  }

  function handleArchived(id: string) {
    setArticles(articles.filter((a) => a.id !== id));
    setArchivedCount((c) => c + 1);
    refreshInsights();
  }

  function handleRestored(id: string) {
    setArchivedItems((prev) => prev.filter((a) => a.id !== id));
    setArchivedCount((c) => Math.max(0, c - 1));
    refreshInsights();
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="w-6 h-6 text-accent animate-spin" />
      </div>
    );
  }

  if (articles.length === 0 && archivedCount === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-muted gap-3">
        <Inbox className="w-12 h-12" />
        <p className="text-sm">No articles yet.</p>
        <p className="text-xs">
          Add keywords and click &quot;Fetch Now&quot; to get started.
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-3">
      {articles.map((article) => (
        <NewsCard
          key={article.id}
          article={article}
          isNew={newIds.has(article.id)}
          onRemoved={handleRemoved}
          onArchived={handleArchived}
        />
      ))}

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
              {archivedItems.map((item) => (
                <NewsCard
                  key={item.id}
                  article={item}
                  onRemoved={handleRemoved}
                  onRestored={handleRestored}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
