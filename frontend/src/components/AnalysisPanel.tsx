"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Sparkles,
  RefreshCw,
  Loader2,
  Newspaper,
  AlertTriangle,
  TrendingUp,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  BarChart3,
  Clock,
} from "lucide-react";
import { useStore } from "@/stores/useStore";
import { timeAgo } from "@/lib/utils";
import {
  fetchInsightSummary,
  fetchTopicInsight,
  fetchTrending,
  type InsightSummary,
  type TopicInsight,
  type TrendingData,
} from "@/lib/api";
import MacroAnalysisPanel from "./MacroAnalysisPanel";
import AnalysisRichText from "./AnalysisRichText";

const EMPTY_SUMMARY: InsightSummary = {
  total_articles: 0,
  important_count: 0,
  source_distribution: {},
  sentiment_distribution: {},
  top_events: [],
};

const EMPTY_INSIGHT: TopicInsight = {
  window_hours: 24,
  article_count: 0,
  previous_count: 0,
  trend_delta: 0,
  sentiment_distribution: {},
  top_tags: [],
};


export default function AnalysisPanel() {
  const activeTopicId = useStore((s) => s.activeTopicId);
  const refreshKey = useStore((s) => s.insightRefreshKey);
  const hydrateLiveSummary = useStore((s) => s.hydrateLiveSummary);
  const startLiveSummaryGeneration = useStore((s) => s.startLiveSummaryGeneration);
  const analysisTabByTopic = useStore((s) => s.analysisTabByTopic);
  const analysisWindowByTopic = useStore((s) => s.analysisWindowByTopic);
  const setAnalysisTab = useStore((s) => s.setAnalysisTab);
  const setAnalysisWindow = useStore((s) => s.setAnalysisWindow);
  const getActionState = useStore((s) => s.getActionState);
  const liveSlice = useStore((s) =>
    s.activeTopicId != null ? s.liveSummaryByTopic[s.activeTopicId] : undefined
  );

  const aiText = liveSlice?.content ?? "";
  const aiGeneratedAt = liveSlice?.generatedAt ?? null;
  const aiCitations = liveSlice?.citations ?? [];
  const isGenerating = liveSlice?.isGenerating ?? false;

  const activeTab = activeTopicId != null ? (analysisTabByTopic[activeTopicId] ?? "realtime") : "realtime";
  const window = activeTopicId != null ? (analysisWindowByTopic[activeTopicId] ?? "24h") : "24h";
  const [stats, setStats] = useState<InsightSummary>(EMPTY_SUMMARY);
  const [insight, setInsight] = useState<TopicInsight>(EMPTY_INSIGHT);
  const [trending, setTrending] = useState<TrendingData | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const liveActionRunning =
    activeTopicId != null &&
    getActionState(`task:live-summary:${activeTopicId}`).status === "running";

  useEffect(() => {
    if (activeTopicId == null) return;
    let cancelled = false;
    setAnalysisError(null);
    const hours = window === "7d" ? 168 : 24;
    const days = window === "7d" ? 7 : 3;
    fetchInsightSummary(activeTopicId, hours).then((d) => { if (!cancelled) setStats(d); }).catch((e) => {
      if (process.env.NODE_ENV === "development") console.warn("[fetch]", e);
      if (!cancelled) setAnalysisError("Some analytics data failed to load.");
    });
    fetchTopicInsight(activeTopicId, window).then((d) => { if (!cancelled) setInsight(d); }).catch((e) => {
      if (process.env.NODE_ENV === "development") console.warn("[fetch]", e);
      if (!cancelled) setAnalysisError("Some analytics data failed to load.");
    });
    fetchTrending(activeTopicId, days).then((d) => { if (!cancelled) setTrending(d); }).catch((e) => {
      if (process.env.NODE_ENV === "development") console.warn("[fetch]", e);
      if (!cancelled) setAnalysisError("Some analytics data failed to load.");
    });
    return () => { cancelled = true; };
  }, [activeTopicId, window, refreshKey]);

  useEffect(() => {
    if (activeTopicId == null) return;
    void hydrateLiveSummary(activeTopicId);
  }, [activeTopicId, hydrateLiveSummary]);

  const handleGenerate = useCallback(() => {
    if (activeTopicId == null || isGenerating || liveActionRunning) return;
    void startLiveSummaryGeneration(activeTopicId);
  }, [activeTopicId, isGenerating, liveActionRunning, startLiveSummaryGeneration]);

  const sentDist = insight.sentiment_distribution;
  const sentTotal = Object.values(sentDist).reduce((a, b) => a + b, 0) || 1;
  const negativeRate = sentTotal > 0 ? (sentDist.negative ?? 0) / sentTotal : 0;
  const importantRate = insight.article_count > 0 ? stats.important_count / insight.article_count : 0;
  const avgRelevance = trending?.avg_topic_relevance ?? 0;

  const prevCount = insight.previous_count ?? 0;
  const surgeRate = prevCount > 0 ? insight.trend_delta / prevCount : 0;

  const alertSignals: { level: "high" | "medium"; text: string }[] = [];
  if (negativeRate >= 0.4) alertSignals.push({ level: "high", text: `Negative sentiment at ${Math.round(negativeRate * 100)}%` });
  else if (negativeRate >= 0.3) alertSignals.push({ level: "medium", text: `Negative sentiment elevated at ${Math.round(negativeRate * 100)}%` });
  if (surgeRate >= 1.0) alertSignals.push({ level: "medium", text: `Volume surge +${Math.round(surgeRate * 100)}% vs previous period` });
  if (importantRate >= 0.4) alertSignals.push({ level: "medium", text: `Important article density ${Math.round(importantRate * 100)}%` });

  const renderLiveTab = () => (
    <div className="space-y-5">
      {/* ── AI Analysis ── */}
      <div>
        {analysisError && (
          <div className="mb-2 rounded-md border border-important/25 bg-important/10 px-2.5 py-1.5 text-[11px] text-important">
            {analysisError}
          </div>
        )}
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted flex items-center gap-1.5">
            <Sparkles className="w-3.5 h-3.5 text-accent" />
            AI Analysis
          </h2>
          <div className="flex items-center gap-1.5">
            {aiGeneratedAt && (
              <span className="text-[10px] text-muted flex items-center gap-0.5">
                <Clock className="w-2.5 h-2.5" />
                {timeAgo(aiGeneratedAt)}
              </span>
            )}
            <button
              onClick={handleGenerate}
              disabled={isGenerating || liveActionRunning}
              className="p-1 rounded text-muted hover:text-foreground hover:bg-surface-hover transition-colors disabled:opacity-40"
              title={aiText ? "Regenerate" : "Generate AI Analysis"}
            >
              <RefreshCw className={`w-3 h-3 ${isGenerating ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>

        {isGenerating && !aiText && (
          <div className="flex items-center gap-2 py-4">
            <Loader2 className="w-3.5 h-3.5 text-accent animate-spin shrink-0" />
            <span className="text-[11px] text-muted">Generating overview in background…</span>
          </div>
        )}
        {isGenerating && aiText && (
          <div className="mb-1.5 flex items-center gap-1.5">
            <Loader2 className="w-3 h-3 text-accent animate-spin shrink-0" />
            <span className="text-[10px] text-muted">Updating…</span>
          </div>
        )}
        {aiText && (
          <AnalysisRichText content={aiText} citations={aiCitations} />
        )}
        {!aiText && !isGenerating && (
          <button
            onClick={handleGenerate}
            disabled={isGenerating || liveActionRunning}
            className="w-full py-4 rounded-lg border border-dashed border-border text-center hover:border-accent/40 hover:bg-accent/5 transition-colors group disabled:opacity-50"
          >
            <Sparkles className="w-4 h-4 text-muted group-hover:text-accent mx-auto mb-1" />
            <span className="text-[11px] text-muted group-hover:text-foreground">Generate AI Analysis</span>
          </button>
        )}
      </div>

      {/* ── Divider + window toggle ── */}
      <div className="border-t border-border pt-4 flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted flex items-center gap-1.5">
          <BarChart3 className="w-3.5 h-3.5" />
          Signals
        </h2>
        <div className="flex gap-1">
          {(["24h", "7d"] as const).map((w) => (
            <button
              key={w}
              onClick={() => activeTopicId != null && setAnalysisWindow(activeTopicId, w)}
              className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
                window === w ? "bg-accent/15 text-accent" : "text-muted hover:text-foreground"
              }`}
            >
              {w}
            </button>
          ))}
        </div>
      </div>
      <p className="text-[10px] text-muted -mt-2">
        Timeline uses article publish time when available; falls back to fetch time.
      </p>

      <div className="space-y-4">
        {/* ── Alert Signals (only when present) ── */}
        {alertSignals.length > 0 && (
          <div className="space-y-1.5">
            {alertSignals.map((sig) => (
              <div
                key={sig.text}
                className={`px-3 py-2 rounded-lg text-[11px] font-medium border flex items-center gap-2 ${
                  sig.level === "high"
                    ? "bg-negative/10 border-negative/30 text-negative"
                    : "bg-important/10 border-important/30 text-important"
                }`}
              >
                <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                {sig.text}
              </div>
            ))}
          </div>
        )}

        {/* ── 4 Stats ── */}
        <div className="grid grid-cols-2 gap-2">
          <StatCard
            icon={<Newspaper className="w-3.5 h-3.5 text-muted" />}
            label="Articles"
            value={insight.article_count}
          />
          <StatCard
            icon={<AlertTriangle className="w-3.5 h-3.5 text-important" />}
            label="Important"
            value={stats.important_count}
          />
          <StatCard
            icon={
              insight.trend_delta > 0
                ? <ArrowUpRight className="w-3.5 h-3.5 text-positive" />
                : insight.trend_delta < 0
                  ? <ArrowDownRight className="w-3.5 h-3.5 text-negative" />
                  : <Minus className="w-3.5 h-3.5 text-muted" />
            }
            label={`vs prev ${window}`}
            value={`${insight.trend_delta > 0 ? "+" : ""}${insight.trend_delta}`}
            valueColor={insight.trend_delta > 0 ? "text-positive" : insight.trend_delta < 0 ? "text-negative" : "text-muted"}
          />
          <StatCard
            icon={<TrendingUp className="w-3.5 h-3.5 text-accent" />}
            label="Topic Match"
            value={avgRelevance > 0 ? `${Math.round(avgRelevance * 100)}%` : "—"}
            valueColor="text-accent"
          />
        </div>

        {/* ── Sentiment ── */}
        <div>
          <h3 className="text-[10px] font-semibold uppercase tracking-wider text-muted mb-2">Sentiment</h3>
          <div className="space-y-2">
            <SentimentBar label="Positive" count={sentDist.positive ?? 0} total={sentTotal} color="bg-positive" />
            <SentimentBar label="Neutral"  count={sentDist.neutral  ?? 0} total={sentTotal} color="bg-muted/60" />
            <SentimentBar label="Negative" count={sentDist.negative ?? 0} total={sentTotal} color="bg-negative" />
          </div>
        </div>

        {/* ── Top Tags (always show full list from API) ── */}
        {insight.top_tags.length > 0 && (
          <div>
            <h3 className="text-[10px] font-semibold uppercase tracking-wider text-muted mb-2">Top Tags</h3>
            <div className="flex flex-wrap gap-1.5">
              {insight.top_tags.map(({ tag, count }) => (
                <span key={tag} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] bg-surface-hover text-muted">
                  {tag}
                  <span className="text-[9px] opacity-50 font-medium">{count}</span>
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );

  return (
    <div className="flex-4 min-w-[320px] bg-surface border-l border-border overflow-y-auto flex flex-col relative">
      <div className="p-4 space-y-4 flex-1">
        <div className="rounded-lg border border-border p-1 bg-surface shadow-sm">
          <div className="grid grid-cols-2 gap-1">
            <button
              onClick={() => activeTopicId != null && setAnalysisTab(activeTopicId, "realtime")}
              className={`px-2 py-1.5 rounded text-[11px] font-semibold transition-colors ${
                activeTab === "realtime" ? "bg-accent/20 text-accent" : "text-muted hover:text-foreground"
              }`}
            >
              Realtime
            </button>
            <button
              onClick={() => activeTopicId != null && setAnalysisTab(activeTopicId, "overview")}
              className={`px-2 py-1.5 rounded text-[11px] font-semibold transition-colors ${
                activeTab === "overview" ? "bg-accent/20 text-accent" : "text-muted hover:text-foreground"
              }`}
            >
              Knowledge
            </button>
          </div>
        </div>

        {activeTab === "realtime" ? (
          renderLiveTab()
        ) : (
          <MacroAnalysisPanel
            activeTopicId={activeTopicId}
            trending={trending}
          />
        )}
      </div>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  valueColor,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | string;
  valueColor?: string;
}) {
  return (
    <div className="px-2.5 py-2 rounded-lg bg-background border border-border shadow-sm">
      <div className="flex items-center gap-1.5 mb-0.5">
        {icon}
        <span className="text-[9px] text-muted uppercase">{label}</span>
      </div>
      <span className={`text-sm font-bold ${valueColor || "text-foreground"}`}>{value}</span>
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
      <div className="flex-1 h-2 rounded-full bg-surface-hover overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-[10px] text-muted tabular-nums w-5 text-right">{count}</span>
    </div>
  );
}
