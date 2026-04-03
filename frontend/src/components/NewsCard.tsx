"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import {
  ExternalLink,
  Sparkles,
  Shield,
  Bookmark,
  Ellipsis,
} from "lucide-react";
import { type Article } from "@/lib/api";
import { useStore } from "@/stores/useStore";
import ArticleContextMenu from "./ArticleContextMenu";
import { effectiveImportance, parseTags } from "@/lib/utils";
import { IMPORTANCE_THRESHOLD } from "@/lib/constants";
import { shouldShowTrackingPin, sentimentConfig } from "./contentCardShared";

export default function NewsCard({
  article,
  isNew,
  onRemoved,
  onArchived,
  onRestored,
}: {
  article: Article;
  isNew?: boolean;
  onRemoved?: (id: string) => void;
  onArchived?: (id: string) => void;
  onRestored?: (id: string) => void;
}) {
  const setSelectedArticle = useStore((s) => s.setSelectedArticle);
  const setChatOpen = useStore((s) => s.setChatOpen);
  const [isKept, setIsKept] = useState(!!article.is_kept);
  const [curSentiment, setCurSentiment] = useState(article.sentiment);
  const [curImportance, setCurImportance] = useState(article.importance);

  const sentiment = sentimentConfig[curSentiment] ?? sentimentConfig.neutral;
  const SentimentIcon = sentiment.icon;
  const tags = parseTags(article.tags);
  const effImp = effectiveImportance(curImportance, article.published_at ?? article.created_at);
  const isImportant = effImp >= IMPORTANCE_THRESHOLD;
  const isArchived = article.status === "archived";
  const showTrackingPin = shouldShowTrackingPin(isKept);

  // Context menu
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number } | null>(null);

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    setCtxMenu({ x: e.clientX, y: e.clientY });
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      onContextMenu={handleContextMenu}
      className={`group relative p-4 rounded-xl shadow-sm hover:shadow-md transition-all border ${
        isArchived
          ? "border-border/50 bg-surface/50 opacity-70"
          : isImportant
            ? "border-important/40 bg-important/5 hover:border-important/60"
            : "border-border bg-surface hover:border-accent/40"
      }`}
    >
      {/* badges row */}
      <div className="flex items-center gap-2 mb-1.5">
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
        {article.source_score > 0 && (
          <span
            className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
            title={`Source quality score: ${(article.source_score * 100).toFixed(0)}%`}
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

        {/* Status indicators (right side) */}
        <div className="ml-auto flex items-center gap-1.5">
          {showTrackingPin && !isArchived && (
            <span className="px-1 py-0.5 rounded text-[9px] font-bold uppercase bg-amber-500/15 text-amber-500" title="Pinned for tracking">
              PIN
            </span>
          )}
          {isKept && (
            <Bookmark className="w-3.5 h-3.5 text-accent fill-accent/30" />
          )}
        </div>
      </div>

      {/* Dual date line */}
      <div className="flex items-center gap-3 mb-2 text-[10px] text-muted">
        {article.published_at && (
          <span>
            <span className="uppercase tracking-wide font-medium mr-1">Published</span>
            {article.published_at.slice(0, 16)}
          </span>
        )}
        {article.created_at && (
          <span>
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
      <div className="flex items-center gap-2">
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
        <span className="ml-auto text-[10px] text-muted">
          {article.source || "web"}
        </span>
        <button
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            setCtxMenu({ x: rect.right - 180, y: rect.bottom + 8 });
          }}
          className="inline-flex items-center justify-center rounded-md p-1 text-muted hover:bg-surface-hover hover:text-foreground transition-colors md:hidden"
          aria-label="Open article actions"
        >
          <Ellipsis className="h-3.5 w-3.5" />
        </button>
      </div>

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
