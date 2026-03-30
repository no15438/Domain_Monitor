"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ExternalLink,
  Sparkles,
  Layers,
  Shield,
  ChevronDown,
  ChevronUp,
  Bookmark,
} from "lucide-react";
import type { Article } from "@/lib/api";
import { fetchEventAlternatives } from "@/lib/api";
import { useStore } from "@/stores/useStore";
import ArticleContextMenu from "./ArticleContextMenu";
import { effectiveImportance, parseTags } from "@/lib/utils";
import { IMPORTANCE_THRESHOLD } from "@/lib/constants";
import { shouldShowTrackingPin, sentimentConfig } from "./contentCardShared";

export default function EventCard({
  article,
  isNew,
  isHighlighted,
  onRemoved,
  onArchived,
  onRestored,
}: {
  article: Article;
  isNew?: boolean;
  isHighlighted?: boolean;
  onRemoved?: (id: string) => void;
  onArchived?: (id: string) => void;
  onRestored?: (id: string) => void;
}) {
  const setSelectedArticle = useStore((s) => s.setSelectedArticle);
  const setChatOpen = useStore((s) => s.setChatOpen);
  const [curSentiment, setCurSentiment] = useState(article.sentiment);
  const [curImportance, setCurImportance] = useState(article.importance);
  const [isKept, setIsKept] = useState(!!article.is_kept);
  const sentiment = sentimentConfig[curSentiment] ?? sentimentConfig.neutral;
  const SentimentIcon = sentiment.icon;
  const tags = parseTags(article.tags);
  const effImp = effectiveImportance(curImportance, article.published_at ?? article.created_at);
  const isImportant = effImp >= IMPORTANCE_THRESHOLD;
  const hasAlternatives = article.event_size > 1 && !!article.event_id;
  const isArchived = article.status === "archived";
  const showTrackingPin = shouldShowTrackingPin(isKept);

  const [expanded, setExpanded] = useState(false);
  const [alternatives, setAlternatives] = useState<Article[]>([]);
  const [loadingAlt, setLoadingAlt] = useState(false);

  // Context menu
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number } | null>(null);

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    setCtxMenu({ x: e.clientX, y: e.clientY });
  };

  async function toggleAlternatives() {
    if (expanded) {
      setExpanded(false);
      return;
    }
    if (alternatives.length === 0 && article.event_id) {
      setLoadingAlt(true);
      const data = await fetchEventAlternatives(article.event_id);
      setAlternatives(data.articles.filter((a) => a.id !== article.id));
      setLoadingAlt(false);
    }
    setExpanded(true);
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      onContextMenu={handleContextMenu}
      className={`group relative rounded-xl shadow-sm hover:shadow-md transition-all border ${
        isArchived
          ? "border-border/50 bg-surface/50 opacity-70"
          : isHighlighted
            ? "border-accent bg-accent/5 ring-1 ring-accent/30"
            : isImportant
              ? "border-important/40 bg-important/5 hover:border-important/60"
              : "border-border bg-surface hover:border-accent/40"
      }`}
    >
      <div className="p-4">
        {/* badges row */}
        <div className="flex flex-wrap items-center gap-1.5 mb-1.5">
          {isNew && (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-accent text-white animate-pulse">
              NEW
            </span>
          )}
          {isArchived && (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-muted/20 text-muted">
              Archived
            </span>
          )}
          {isImportant && !isArchived && (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-important/20 text-important">
              Important
            </span>
          )}
          <span
            className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium ${sentiment.bg} ${sentiment.color}`}
          >
            <SentimentIcon className="w-3 h-3" />
            {curSentiment}
          </span>
          {article.event_size > 1 && (
            <span
              className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-accent/10 text-accent"
              title={`${article.event_size} sources report this event`}
            >
              <Layers className="w-3 h-3" />
              {article.event_size}
            </span>
          )}
          {article.source_score > 0 && (
            <span
              className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
              title={`Source quality: ${(article.source_score * 100).toFixed(0)}%`}
            >
              <Shield className="w-3 h-3" />
              {(article.source_score * 100).toFixed(0)}
            </span>
          )}
          {article.source_type && article.source_type !== "search" && (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-surface-hover text-muted uppercase">
              {article.source_type}
            </span>
          )}
          {(showTrackingPin && !isArchived) || isKept ? (
            <div className="ml-auto flex items-center gap-1.5 shrink-0">
              {showTrackingPin && !isArchived && (
                <span className="px-1 py-0.5 rounded text-[9px] font-bold uppercase bg-amber-500/15 text-amber-500" title="Pinned for tracking">
                  PIN
                </span>
              )}
              {isKept && (
                <Bookmark className="w-3.5 h-3.5 text-accent fill-accent/30" />
              )}
            </div>
          ) : null}
        </div>

        {/* Date line */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 mb-2 text-[10px] text-muted">
          {article.published_at && (
            <span className="whitespace-nowrap">
              <span className="uppercase tracking-wide font-medium mr-1">Published</span>
              {article.published_at.slice(0, 16)}
            </span>
          )}
          {article.created_at && (
            <span className="whitespace-nowrap">
              <span className="uppercase tracking-wide font-medium mr-1">Fetched</span>
              {article.created_at.slice(0, 16)}
            </span>
          )}
        </div>

        {/* title */}
        <h3 className="text-sm font-semibold leading-snug mb-1.5 line-clamp-2">
          {article.title}
        </h3>

        {/* summary */}
        {article.summary && (
          <p className="text-xs text-muted leading-relaxed mb-2 line-clamp-2">
            {article.summary}
          </p>
        )}

        {/* tags */}
        {tags.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-2">
            {tags.slice(0, 4).map((tag) => (
              <span
                key={tag}
                className="px-1.5 py-0.5 rounded text-[10px] bg-surface-hover text-muted"
              >
                #{tag}
              </span>
            ))}
          </div>
        )}

        {/* actions row */}
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            onClick={() => { setSelectedArticle(article); setChatOpen(true); }}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium bg-accent/10 text-accent-hover hover:bg-accent/20 transition-colors"
          >
            <Sparkles className="w-3 h-3" />
            Ask AI
          </button>
          {article.url && (
            <a
              href={article.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] text-muted hover:text-foreground transition-colors"
            >
              <ExternalLink className="w-3 h-3" />
              Source
            </a>
          )}
          {hasAlternatives && (
            <button
              onClick={toggleAlternatives}
              className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] text-muted hover:text-foreground transition-colors"
            >
              {expanded ? (
                <ChevronUp className="w-3 h-3" />
              ) : (
                <ChevronDown className="w-3 h-3" />
              )}
              {article.event_size - 1} more source{article.event_size > 2 ? "s" : ""}
            </button>
          )}
          <span className="ml-auto shrink-0 text-[10px] text-muted truncate max-w-[40%]" title={article.source || "web"}>
            {article.source || "web"}
          </span>
        </div>
      </div>

      {/* Alternatives (expanded) */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden border-t border-border bg-surface-hover/30"
          >
            <div className="px-4 py-2 space-y-2">
              {loadingAlt ? (
                <p className="text-[10px] text-muted py-2">Loading sources...</p>
              ) : alternatives.length === 0 ? (
                <p className="text-[10px] text-muted py-2">No alternative sources found.</p>
              ) : (
                alternatives.map((alt) => (
                  <AlternativeRow key={alt.id} article={alt} />
                ))
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Context menu */}
      {ctxMenu && (
        <ArticleContextMenu
          x={ctxMenu.x}
          y={ctxMenu.y}
          article={article}
          sentiment={curSentiment}
          importance={curImportance}
          isKept={isKept}
          onClose={() => setCtxMenu(null)}
          onSentimentChange={setCurSentiment}
          onImportanceChange={setCurImportance}
          onKeptChange={setIsKept}
          onArchived={() => onArchived?.(article.id)}
          onRestored={() => onRestored?.(article.id)}
          onDeleted={() => onRemoved?.(article.id)}
        />
      )}
    </motion.div>
  );
}

function AlternativeRow({ article }: { article: Article }) {
  return (
    <div className="flex items-center gap-2 py-1.5 border-b border-border/50 last:border-0">
      <div className="flex-1 min-w-0">
        <p className="text-[11px] font-medium leading-snug line-clamp-1">
          {article.title}
        </p>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-[9px] text-muted">{article.source || "web"}</span>
          {article.source_score > 0 && (
            <span className="text-[9px] text-emerald-400">
              score {(article.source_score * 100).toFixed(0)}
            </span>
          )}
          <span className="text-[9px] text-muted">{article.source_type}</span>
        </div>
      </div>
      {article.published_at && (
        <span className="shrink-0 text-[9px] text-muted whitespace-nowrap">{article.published_at.slice(0, 16)}</span>
      )}
      {article.url && (
        <a
          href={article.url}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 p-1 text-muted hover:text-foreground"
        >
          <ExternalLink className="w-3 h-3" />
        </a>
      )}
    </div>
  );
}
