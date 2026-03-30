"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Flame,
  AlertTriangle,
  Newspaper,
  TrendingUp,
  TrendingDown,
  Minus,
  Shield,
  Layers,
} from "lucide-react";
import { useStore } from "@/stores/useStore";
import { fetchInsightSummary, type InsightSummary, type EventCluster } from "@/lib/api";
import { parseTags } from "@/lib/utils";

const EMPTY: InsightSummary = {
  total_articles: 0,
  important_count: 0,
  source_distribution: {},
  sentiment_distribution: {},
  top_events: [],
};

const sentimentIcon = {
  positive: TrendingUp,
  negative: TrendingDown,
  neutral: Minus,
} as const;

const sentimentColor = {
  positive: "text-positive",
  negative: "text-negative",
  neutral: "text-muted",
} as const;

export default function SummaryStrip() {
  const activeTopicId = useStore((s) => s.activeTopicId);
  const refreshKey = useStore((s) => s.insightRefreshKey);
  const [data, setData] = useState<InsightSummary>(EMPTY);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const setHighlightedEventId = useStore((s) => s.setHighlightedEventId);

  useEffect(() => {
    fetchInsightSummary(activeTopicId, 24)
      .then(setData)
      .catch((e) => {
        if (process.env.NODE_ENV === "development") console.warn("[fetch]", e);
      });
  }, [activeTopicId, refreshKey]);

  function handleEventClick(eventId: string) {
    const next = selectedEventId === eventId ? null : eventId;
    setSelectedEventId(next);
    setHighlightedEventId(next);
  }

  const topEvents = data.top_events.slice(0, 3);

  return (
    <div className="border-b border-border bg-surface/40 backdrop-blur-sm">
      {/* Stat counters */}
      <div className="flex items-center gap-4 px-5 py-2.5 overflow-x-auto">
        <StatBadge
          icon={<Newspaper className="w-3.5 h-3.5" />}
          label="24h Articles"
          value={data.total_articles}
        />
        <StatBadge
          icon={<AlertTriangle className="w-3.5 h-3.5 text-important" />}
          label="Important"
          value={data.important_count}
          accent
        />
        <StatBadge
          icon={<TrendingUp className="w-3.5 h-3.5 text-positive" />}
          label="Positive"
          value={data.sentiment_distribution.positive ?? 0}
        />
        <StatBadge
          icon={<TrendingDown className="w-3.5 h-3.5 text-negative" />}
          label="Negative"
          value={data.sentiment_distribution.negative ?? 0}
        />

        {Object.keys(data.source_distribution).length > 0 && (
          <div className="ml-auto flex items-center gap-1.5">
            {Object.entries(data.source_distribution)
              .slice(0, 4)
              .map(([src, cnt]) => (
                <span
                  key={src}
                  className="px-1.5 py-0.5 rounded text-[10px] bg-surface-hover text-muted uppercase"
                >
                  {src} {cnt}
                </span>
              ))}
          </div>
        )}
      </div>

      {/* Top events */}
      {topEvents.length > 0 && (
        <div className="flex gap-3 px-5 pb-3 overflow-x-auto">
          {topEvents.map((ev, i) => (
            <TopEventCard
              key={ev.id}
              event={ev}
              rank={i + 1}
              isSelected={selectedEventId === ev.id}
              onClick={() => handleEventClick(ev.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function StatBadge({
  icon,
  label,
  value,
  accent,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  accent?: boolean;
}) {
  return (
    <div className="flex items-center gap-1.5 whitespace-nowrap">
      {icon}
      <span className="text-[10px] text-muted">{label}</span>
      <span
        className={`text-xs font-semibold ${accent ? "text-important" : "text-foreground"}`}
      >
        {value}
      </span>
    </div>
  );
}

function TopEventCard({
  event,
  rank,
  isSelected,
  onClick,
}: {
  event: EventCluster;
  rank: number;
  isSelected: boolean;
  onClick: () => void;
}) {
  const sentiment = (event.sentiment || "neutral") as keyof typeof sentimentIcon;
  const SIcon = sentimentIcon[sentiment] ?? Minus;
  const sColor = sentimentColor[sentiment] ?? "text-muted";
  const tags = parseTags(event.tags).slice(0, 2);

  return (
    <motion.button
      onClick={onClick}
      whileHover={{ scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
      className={`shrink-0 w-64 p-3 rounded-lg border text-left transition-colors ${
        isSelected
          ? "border-accent bg-accent/10"
          : "border-border bg-surface hover:border-accent/30"
      }`}
    >
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="w-4 h-4 rounded-full bg-accent/20 text-accent text-[10px] font-bold flex items-center justify-center">
          {rank}
        </span>
        <SIcon className={`w-3 h-3 ${sColor}`} />
        {event.source_count > 1 && (
          <span className="inline-flex items-center gap-0.5 text-[10px] text-accent">
            <Layers className="w-3 h-3" />
            {event.source_count}
          </span>
        )}
        {event.source_score > 0 && (
          <span className="inline-flex items-center gap-0.5 text-[10px] text-emerald-400">
            <Shield className="w-3 h-3" />
            {(event.source_score * 100).toFixed(0)}
          </span>
        )}
        <span className="ml-auto text-[9px] text-muted truncate max-w-[60px]">
          {event.canonical_source || "web"}
        </span>
      </div>
      <p className="text-xs font-medium leading-snug line-clamp-2 mb-1">
        {event.title}
      </p>
      {event.summary && (
        <p className="text-[10px] text-muted leading-relaxed line-clamp-1">
          {event.summary}
        </p>
      )}
      {tags.length > 0 && (
        <div className="flex gap-1 mt-1.5">
          {tags.map((t) => (
            <span key={t} className="px-1 py-0.5 rounded text-[9px] bg-surface-hover text-muted">
              #{t}
            </span>
          ))}
        </div>
      )}
    </motion.button>
  );
}
