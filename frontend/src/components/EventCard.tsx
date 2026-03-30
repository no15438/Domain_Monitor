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
  Globe,
} from "lucide-react";
import type { EventCluster, ClusterSource, PreviewSource } from "@/lib/api";
import {
  fetchEventDetail,
  archiveEvent,
  restoreEvent,
  deleteEvent,
  toggleEventKept,
} from "@/lib/api";
import { useStore } from "@/stores/useStore";
import { effectiveImportance, parseTags } from "@/lib/utils";
import { IMPORTANCE_THRESHOLD } from "@/lib/constants";
import { shouldShowTrackingPin, sentimentConfig } from "./contentCardShared";

export default function EventCard({
  event,
  isNew,
  isHighlighted,
  onRemoved,
  onArchived,
  onRestored,
}: {
  event: EventCluster;
  isNew?: boolean;
  isHighlighted?: boolean;
  onRemoved?: (id: string) => void;
  onArchived?: (id: string) => void;
  onRestored?: (id: string) => void;
}) {
  const setSelectedEventContext = useStore((s) => s.setSelectedEventContext);
  const setChatOpen = useStore((s) => s.setChatOpen);

  const [curSentiment, setCurSentiment] = useState(event.sentiment);
  const [curImportance, setCurImportance] = useState(event.importance);
  const [isKept, setIsKept] = useState(!!event.is_kept);

  const sentiment = sentimentConfig[curSentiment] ?? sentimentConfig.neutral;
  const SentimentIcon = sentiment.icon;
  const tags = parseTags(event.tags);

  // Parse preview_sources from JSON string or array
  const previewSources: PreviewSource[] = (() => {
    const raw = event.preview_sources;
    if (!raw) return [];
    if (Array.isArray(raw)) return raw as PreviewSource[];
    try { return JSON.parse(raw as string) as PreviewSource[]; }
    catch { return []; }
  })();
  const effImp = effectiveImportance(
    curImportance,
    event.published_at ?? event.created_at ?? event.first_seen_at ?? "",
  );
  const isImportant = effImp >= IMPORTANCE_THRESHOLD;
  const hasMultipleSources = event.source_count > 1;
  const isArchived = event.status === "archived";
  const showTrackingPin = shouldShowTrackingPin(isKept);

  const [expanded, setExpanded] = useState(false);
  const [sources, setSources] = useState<ClusterSource[]>([]);
  const [loadingSources, setLoadingSources] = useState(false);

  const [ctxVisible, setCtxVisible] = useState(false);

  async function toggleSources() {
    if (expanded) {
      setExpanded(false);
      return;
    }
    if (sources.length === 0) {
      setLoadingSources(true);
      const data = await fetchEventDetail(event.id);
      // Show all sources (canonical marked separately); full detail also provides canonical_content for chat
      setSources(data.sources ?? []);
      setLoadingSources(false);
    }
    setExpanded(true);
  }

  async function handleArchive() {
    await archiveEvent(event.id);
    onArchived?.(event.id);
  }

  async function handleRestore() {
    await restoreEvent(event.id);
    onRestored?.(event.id);
  }

  async function handleDelete() {
    await deleteEvent(event.id);
    onRemoved?.(event.id);
  }

  async function handleToggleKept() {
    const next = !isKept;
    setIsKept(next);
    await toggleEventKept(event.id, next);
  }

  function handleAskAI() {
    setSelectedEventContext({
      event_id: event.id,
      title: event.title,
      summary: event.summary,
      canonical_source: event.canonical_source ?? null,
      canonical_url: event.canonical_url ?? null,
      source_count: event.source_count,
      sentiment: event.sentiment,
      importance: event.importance,
      tags: event.tags,
      first_seen_at: event.first_seen_at ?? null,
      last_seen_at: event.last_seen_at ?? null,
    });
    setChatOpen(true);
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={`group relative rounded-xl shadow-sm hover:shadow-md transition-all border ${
        isArchived
          ? "border-border/50 bg-surface/50 opacity-70"
          : isHighlighted
            ? "border-accent bg-accent/5 ring-1 ring-accent/30"
            : isImportant
              ? "border-important/40 bg-important/5 hover:border-important/60"
              : "border-border bg-surface hover:border-accent/40"
      }`}
      onContextMenu={(e) => { e.preventDefault(); setCtxVisible(true); }}
      onClick={() => ctxVisible && setCtxVisible(false)}
    >
      <div className="p-4">
        {/* Badges row */}
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
          {event.source_count > 0 && (
            <span
              className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-accent/10 text-accent"
              title={`${event.source_count} source${event.source_count !== 1 ? "s" : ""} cover this event`}
            >
              <Layers className="w-3 h-3" />
              {event.source_count}
            </span>
          )}
          {event.source_score > 0 && (
            <span
              className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
              title={`Source quality: ${(event.source_score * 100).toFixed(0)}%`}
            >
              <Shield className="w-3 h-3" />
              {(event.source_score * 100).toFixed(0)}
            </span>
          )}
          {event.source_type && event.source_type !== "search" && (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-surface-hover text-muted uppercase">
              {event.source_type}
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

        {/* Time window */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 mb-2 text-[10px] text-muted">
          {event.first_seen_at && (
            <span className="whitespace-nowrap">
              <span className="uppercase tracking-wide font-medium mr-1">First seen</span>
              {event.first_seen_at.slice(0, 16)}
            </span>
          )}
          {event.last_seen_at && event.last_seen_at !== event.first_seen_at && (
            <span className="whitespace-nowrap">
              <span className="uppercase tracking-wide font-medium mr-1">Last seen</span>
              {event.last_seen_at.slice(0, 16)}
            </span>
          )}
        </div>

        {/* Event title */}
        <h3 className="text-sm font-semibold leading-snug mb-1.5 line-clamp-2">
          {event.title}
        </h3>

        {/* Event summary */}
        {event.summary && (
          <p className="text-xs text-muted leading-relaxed mb-2 line-clamp-2">
            {event.summary}
          </p>
        )}

        {/* Tags */}
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

        {/* Preview sources strip — shown when source_count > 1 and detail not yet loaded */}
        {previewSources.length > 0 && !expanded && (
          <div className="flex flex-wrap gap-1 mb-2">
            {previewSources.map((ps, i) => (
              <a
                key={i}
                href={ps.url}
                target="_blank"
                rel="noopener noreferrer"
                title={ps.title}
                className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-surface-hover text-muted hover:text-foreground transition-colors truncate max-w-[140px]"
              >
                <Globe className="w-2.5 h-2.5 shrink-0" />
                {ps.source}
              </a>
            ))}
          </div>
        )}

        {/* Action row */}
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            onClick={handleAskAI}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium bg-accent/10 text-accent-hover hover:bg-accent/20 transition-colors"
          >
            <Sparkles className="w-3 h-3" />
            Ask AI
          </button>

          {event.canonical_url && (
            <a
              href={event.canonical_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] text-muted hover:text-foreground transition-colors"
            >
              <ExternalLink className="w-3 h-3" />
              Source
            </a>
          )}

          {hasMultipleSources && (
            <button
              onClick={toggleSources}
              className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] text-muted hover:text-foreground transition-colors"
            >
              {expanded ? (
                <ChevronUp className="w-3 h-3" />
              ) : (
                <ChevronDown className="w-3 h-3" />
              )}
              {event.source_count - 1} more source{event.source_count > 2 ? "s" : ""}
            </button>
          )}

          {/* Context actions */}
          <div className="ml-auto flex items-center gap-1 shrink-0">
            <button
              onClick={handleToggleKept}
              className="p-1 rounded text-muted hover:text-accent transition-colors"
              title={isKept ? "Unpin" : "Pin for tracking"}
            >
              <Bookmark className={`w-3.5 h-3.5 ${isKept ? "fill-accent/30 text-accent" : ""}`} />
            </button>
            {!isArchived ? (
              <button
                onClick={handleArchive}
                className="p-1 rounded text-[10px] text-muted hover:text-foreground transition-colors"
                title="Archive event"
              >
                Archive
              </button>
            ) : (
              <button
                onClick={handleRestore}
                className="p-1 rounded text-[10px] text-muted hover:text-foreground transition-colors"
                title="Restore event"
              >
                Restore
              </button>
            )}
            <button
              onClick={handleDelete}
              className="p-1 rounded text-[10px] text-muted hover:text-negative transition-colors"
              title="Delete event"
            >
              Delete
            </button>
            <span className="text-[10px] text-muted truncate max-w-[40%]" title={event.canonical_source || "web"}>
              <Globe className="w-3 h-3 inline-block mr-0.5 opacity-50" />
              {event.canonical_source || "web"}
            </span>
          </div>
        </div>
      </div>

      {/* Sources (expanded) */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden border-t border-border bg-surface-hover/30"
          >
            <div className="px-4 py-2 space-y-0">
              {loadingSources ? (
                <p className="text-[10px] text-muted py-2">Loading sources…</p>
              ) : sources.length === 0 ? (
                <p className="text-[10px] text-muted py-2">No sources found.</p>
              ) : (
                sources.map((src) => (
                  <SourceRow key={src.id} source={src} isCanonical={src.is_canonical === 1} />
                ))
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

function SourceRow({ source, isCanonical }: { source: ClusterSource; isCanonical?: boolean }) {
  return (
    <div className="flex items-center gap-2 py-1.5 border-b border-border/50 last:border-0">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 mb-0.5">
          {isCanonical && (
            <span className="px-1 py-0.5 rounded text-[9px] font-semibold bg-accent/10 text-accent uppercase tracking-wide shrink-0">
              Primary
            </span>
          )}
          <p className="text-[11px] font-medium leading-snug line-clamp-1">
            {source.title}
          </p>
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-[9px] text-muted">{source.source || "web"}</span>
          {source.source_score > 0 && (
            <span className="text-[9px] text-emerald-400">
              score {(source.source_score * 100).toFixed(0)}
            </span>
          )}
          <span className="text-[9px] text-muted">{source.source_type}</span>
        </div>
      </div>
      {source.published_at && (
        <span className="shrink-0 text-[9px] text-muted whitespace-nowrap">
          {source.published_at.slice(0, 16)}
        </span>
      )}
      {source.url && (
        <a
          href={source.url}
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
