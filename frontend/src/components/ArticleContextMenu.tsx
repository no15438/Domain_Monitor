"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { createPortal } from "react-dom";
import {
  TrendingUp,
  TrendingDown,
  Minus,
  Bookmark,
  BookmarkCheck,
  Archive,
  ArchiveRestore,
  Trash2,
} from "lucide-react";
import type { Article } from "@/lib/api";
import {
  patchArticle,
  toggleArticleKept,
  deleteArticle,
  archiveArticle,
  restoreArticle,
} from "@/lib/api";
import { useStore } from "@/stores/useStore";

const SENTIMENTS = ["positive", "neutral", "negative"] as const;
const IMPORTANCE_PRESETS = [3, 5, 7, 9] as const;

const sentimentMeta: Record<
  string,
  { icon: typeof TrendingUp; label: string; color: string }
> = {
  positive: { icon: TrendingUp, label: "Positive", color: "text-positive" },
  neutral: { icon: Minus, label: "Neutral", color: "text-muted" },
  negative: { icon: TrendingDown, label: "Negative", color: "text-negative" },
};

interface Props {
  x: number;
  y: number;
  article: Article;
  sentiment: string;
  importance: number;
  isKept: boolean;
  onClose: () => void;
  onSentimentChange: (s: typeof SENTIMENTS[number]) => void;
  onImportanceChange: (v: number) => void;
  onKeptChange: (kept: boolean) => void;
  onArchived: () => void;
  onRestored?: () => void;
  onDeleted: () => void;
}

export default function ArticleContextMenu({
  x,
  y,
  article,
  sentiment,
  importance,
  isKept,
  onClose,
  onSentimentChange,
  onImportanceChange,
  onKeptChange,
  onArchived,
  onRestored,
  onDeleted,
}: Props) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x, y });
  const isArchived = article.status === "archived";
  const addToast = useStore((s) => s.addToast);

  useEffect(() => {
    const menu = menuRef.current;
    if (!menu) return;
    const rect = menu.getBoundingClientRect();
    let nx = x;
    let ny = y;
    if (x + rect.width > window.innerWidth - 8) nx = window.innerWidth - rect.width - 8;
    if (y + rect.height > window.innerHeight - 8) ny = window.innerHeight - rect.height - 8;
    if (nx < 8) nx = 8;
    if (ny < 8) ny = 8;
    setPos({ x: nx, y: ny });
  }, [x, y]);

  const handleClickOutside = useCallback(
    (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    },
    [onClose],
  );

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKey);
    };
  }, [handleClickOutside, onClose]);

  const handleSentiment = async (s: typeof SENTIMENTS[number]) => {
    onSentimentChange(s);
    await patchArticle(article.id, { sentiment: s });
  };

  const handleImportance = async (v: number) => {
    onImportanceChange(v);
    await patchArticle(article.id, { importance: v });
  };

  const handleToggleKept = async () => {
    const next = !isKept;
    onKeptChange(next);
    const ok = await toggleArticleKept(article.id, next);
    if (!ok) onKeptChange(!next);
  };

  const handleArchive = async () => {
    const ok = await archiveArticle(article.id);
    if (ok) {
      onArchived();
    } else {
      addToast("Failed to archive article", "error");
    }
    onClose();
  };

  const handleRestore = async () => {
    const ok = await restoreArticle(article.id);
    if (ok) {
      onRestored?.();
    } else {
      addToast("Failed to restore article", "error");
    }
    onClose();
  };

  const handleDelete = async () => {
    const ok = await deleteArticle(article.id);
    if (ok) {
      onDeleted();
    } else {
      addToast("Failed to delete article", "error");
    }
    onClose();
  };

  return createPortal(
    <>
      {/* invisible overlay to block interactions */}
      <div className="fixed inset-0 z-9998" />
      <div
        ref={menuRef}
        role="menu"
        aria-label="Article actions"
        style={{ left: pos.x, top: pos.y }}
        className="fixed z-9999 w-56 py-1 rounded-xl border border-border bg-surface/95 backdrop-blur-lg shadow-2xl text-xs select-none"
      >
        {/* Sentiment */}
        <div className="px-3 pt-2 pb-1 text-[9px] uppercase tracking-wider text-muted font-semibold">
          Sentiment
        </div>
        {SENTIMENTS.map((s) => {
          const meta = sentimentMeta[s];
          const Icon = meta.icon;
          const active = sentiment === s;
          return (
            <button
              key={s}
              role="menuitem"
              aria-pressed={active}
              onClick={() => handleSentiment(s)}
              className={`w-full flex items-center gap-2 px-3 py-1.5 hover:bg-surface-hover transition-colors ${active ? meta.color + " font-semibold" : "text-foreground"}`}
            >
              <Icon className="w-3.5 h-3.5" aria-hidden="true" />
              <span>{meta.label}</span>
              {active && <span className="ml-auto text-[10px]" aria-hidden="true">✓</span>}
            </button>
          );
        })}

        <div className="my-1 border-t border-border" />

        {/* Importance */}
        <div className="px-3 pt-1 pb-1 text-[9px] uppercase tracking-wider text-muted font-semibold">
          Importance
        </div>
        <div className="flex items-center gap-1 px-3 pb-2">
          {IMPORTANCE_PRESETS.map((v) => (
            <button
              key={v}
              role="menuitem"
              aria-pressed={importance === v}
              aria-label={`Set importance to ${v}`}
              onClick={() => handleImportance(v)}
              className={`w-8 h-6 rounded text-[10px] font-bold transition-colors ${
                importance === v
                  ? v >= 8
                    ? "bg-important/20 text-important"
                    : "bg-accent/15 text-accent"
                  : "text-muted bg-surface-hover hover:bg-surface-hover/80"
              }`}
            >
              {v}
            </button>
          ))}
        </div>

        <div className="my-1 border-t border-border" />

        {/* Bookmark toggle */}
        <button
          role="menuitem"
          onClick={handleToggleKept}
          className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-surface-hover transition-colors text-foreground"
        >
          {isKept ? (
            <>
              <BookmarkCheck className="w-3.5 h-3.5 text-accent" aria-hidden="true" />
              <span>Remove tracking pin</span>
            </>
          ) : (
            <>
              <Bookmark className="w-3.5 h-3.5" aria-hidden="true" />
              <span>Pin for tracking</span>
            </>
          )}
        </button>

        <div className="my-1 border-t border-border" />

        {/* Archive / Restore */}
        {isArchived ? (
          <button
            role="menuitem"
            onClick={handleRestore}
            className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-surface-hover transition-colors text-foreground"
          >
            <ArchiveRestore className="w-3.5 h-3.5" aria-hidden="true" />
            <span>Restore</span>
          </button>
        ) : (
          <button
            role="menuitem"
            onClick={handleArchive}
            className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-surface-hover transition-colors text-foreground"
          >
            <Archive className="w-3.5 h-3.5" aria-hidden="true" />
            <span>Archive</span>
          </button>
        )}

        {/* Delete */}
        <button
          role="menuitem"
          onClick={handleDelete}
          className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-negative/10 transition-colors text-negative"
        >
          <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
          <span>Delete permanently</span>
        </button>
      </div>
    </>,
    document.body,
  );
}
