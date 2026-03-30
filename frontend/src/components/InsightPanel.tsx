"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  TrendingUp,
  TrendingDown,
  BarChart3,
  Tag,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
} from "lucide-react";
import { useStore } from "@/stores/useStore";
import {
  fetchTopicInsight,
  fetchInsightSummary,
  type TopicInsight,
  type InsightSummary,
} from "@/lib/api";

const EMPTY_TOPIC: TopicInsight = {
  window_hours: 24,
  article_count: 0,
  previous_count: 0,
  trend_delta: 0,
  sentiment_distribution: {},
  top_tags: [],
};

const EMPTY_SUMMARY: InsightSummary = {
  total_articles: 0,
  important_count: 0,
  source_distribution: {},
  sentiment_distribution: {},
  top_events: [],
};

export default function InsightPanel() {
  const activeTopicId = useStore((s) => s.activeTopicId);
  const refreshKey = useStore((s) => s.insightRefreshKey);
  const [window, setWindow] = useState<"24h" | "7d">("24h");
  const [topicData, setTopicData] = useState<TopicInsight>(EMPTY_TOPIC);
  const [summaryData, setSummaryData] = useState<InsightSummary>(EMPTY_SUMMARY);

  useEffect(() => {
    let cancelled = false;
    const hours = window === "7d" ? 168 : 24;
    fetchTopicInsight(activeTopicId, window).then((d) => { if (!cancelled) setTopicData(d); }).catch((e) => { if (process.env.NODE_ENV === "development") console.warn("[fetch]", e); });
    fetchInsightSummary(activeTopicId, hours).then((d) => { if (!cancelled) setSummaryData(d); }).catch((e) => { if (process.env.NODE_ENV === "development") console.warn("[fetch]", e); });
    return () => { cancelled = true; };
  }, [activeTopicId, window, refreshKey]);

  const sentDist = topicData.sentiment_distribution;
  const sentTotal = Object.values(sentDist).reduce((a, b) => a + b, 0) || 1;

  const sourceDist = summaryData.source_distribution;
  const sourceTotal = Object.values(sourceDist).reduce((a, b) => a + b, 0) || 1;

  return (
    <div className="w-64 shrink-0 border-l border-border bg-surface/30 overflow-y-auto">
      <div className="p-4 space-y-5">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted flex items-center gap-1.5">
            <BarChart3 className="w-3.5 h-3.5" />
            Insights
          </h2>
          <div className="flex gap-1">
            {(["24h", "7d"] as const).map((w) => (
              <button
                key={w}
                onClick={() => setWindow(w)}
                className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
                  window === w
                    ? "bg-accent/15 text-accent"
                    : "text-muted hover:text-foreground"
                }`}
              >
                {w}
              </button>
            ))}
          </div>
        </div>

        {/* Trend delta */}
        <InsightCard title="Trend">
          <div className="flex items-center gap-2">
            <span className="text-2xl font-bold">{topicData.article_count}</span>
            <span className="text-xs text-muted">articles</span>
          </div>
          <div className="flex items-center gap-1 mt-1">
            {topicData.trend_delta > 0 ? (
              <ArrowUpRight className="w-3.5 h-3.5 text-positive" />
            ) : topicData.trend_delta < 0 ? (
              <ArrowDownRight className="w-3.5 h-3.5 text-negative" />
            ) : (
              <Minus className="w-3.5 h-3.5 text-muted" />
            )}
            <span
              className={`text-xs font-medium ${
                topicData.trend_delta > 0
                  ? "text-positive"
                  : topicData.trend_delta < 0
                    ? "text-negative"
                    : "text-muted"
              }`}
            >
              {topicData.trend_delta > 0 ? "+" : ""}
              {topicData.trend_delta} vs prev
            </span>
          </div>
        </InsightCard>

        {/* Sentiment distribution */}
        <InsightCard title="Sentiment">
          <div className="space-y-2">
            <SentimentBar
              label="Positive"
              count={sentDist.positive ?? 0}
              total={sentTotal}
              color="bg-positive"
            />
            <SentimentBar
              label="Neutral"
              count={sentDist.neutral ?? 0}
              total={sentTotal}
              color="bg-muted"
            />
            <SentimentBar
              label="Negative"
              count={sentDist.negative ?? 0}
              total={sentTotal}
              color="bg-negative"
            />
          </div>
        </InsightCard>

        {/* Source diversity */}
        <InsightCard title="Sources">
          <div className="space-y-1.5">
            {Object.entries(sourceDist)
              .sort((a, b) => b[1] - a[1])
              .slice(0, 5)
              .map(([src, cnt]) => (
                <div key={src} className="flex items-center gap-2">
                  <div className="flex-1 h-1.5 rounded-full bg-surface-hover overflow-hidden">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${(cnt / sourceTotal) * 100}%` }}
                      className="h-full rounded-full bg-accent/60"
                    />
                  </div>
                  <span className="text-[10px] text-muted w-16 text-right uppercase">
                    {src}
                  </span>
                  <span className="text-[10px] font-medium w-5 text-right">
                    {cnt}
                  </span>
                </div>
              ))}
          </div>
        </InsightCard>

        {/* Top tags */}
        {topicData.top_tags.length > 0 && (
          <InsightCard title="Top Tags">
            <div className="flex flex-wrap gap-1.5">
              {topicData.top_tags.slice(0, 8).map(({ tag, count }) => (
                <span
                  key={tag}
                  className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] bg-surface-hover text-muted"
                >
                  <Tag className="w-2.5 h-2.5" />
                  {tag}
                  <span className="text-[9px] opacity-60">{count}</span>
                </span>
              ))}
            </div>
          </InsightCard>
        )}

        {/* Event coverage summary */}
        {summaryData.top_events.length > 0 && (
          <InsightCard title="Coverage">
            <div className="space-y-2">
              {summaryData.top_events.slice(0, 4).map((ev, i) => (
                <div key={`${ev.id || ''}-${i}`} className="flex items-center gap-2">
                  <span className="shrink-0 w-5 h-5 rounded-full bg-accent/10 text-accent text-[10px] font-bold flex items-center justify-center">
                    {ev.source_count ?? 1}
                  </span>
                  <p className="text-[10px] leading-snug line-clamp-1 flex-1">
                    {ev.title}
                  </p>
                </div>
              ))}
            </div>
          </InsightCard>
        )}
      </div>
    </div>
  );
}

function InsightCard({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <h3 className="text-[10px] font-semibold uppercase tracking-wider text-muted mb-2">
        {title}
      </h3>
      {children}
    </div>
  );
}

function SentimentBar({
  label,
  count,
  total,
  color,
}: {
  label: string;
  count: number;
  total: number;
  color: string;
}) {
  const pct = total > 0 ? (count / total) * 100 : 0;
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-muted w-14">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-surface-hover overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          className={`h-full rounded-full ${color}`}
        />
      </div>
      <span className="text-[10px] font-medium w-5 text-right">{count}</span>
    </div>
  );
}
