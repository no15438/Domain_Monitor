"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  RefreshCw,
  MessageSquare,
} from "lucide-react";
import { useStore } from "@/stores/useStore";
import ThemeToggle from "@/components/ThemeToggle";
import { triggerFetch, fetchFetchStatus } from "@/lib/api";
import { runWithAction } from "@/lib/api/shared";

function useLastFetchedLabel(articles: { created_at: string }[]): string | null {
  if (!articles.length) return null;
  const withDate = articles.filter((a) => !!a.created_at);
  if (!withDate.length) return null;
  const latest = withDate.reduce((best, a) =>
    a.created_at > best.created_at ? a : best
  );
  const s = latest.created_at.trim().replace(" ", "T");
  const ts = new Date(s.endsWith("Z") || /[+-]\d{2}:\d{2}$/.test(s) ? s : s + "Z");
  if (isNaN(ts.getTime())) return null;
  const diffMs = Date.now() - ts.getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  return `${Math.floor(diffH / 24)}d ago`;
}

export default function TopicHeader({
  topicName,
  topicColor,
}: {
  topicName: string;
  topicColor: string;
}) {
  const {
    fetchingTopicId,
    setFetchingTopic,
    chatOpen,
    setChatOpen,
    activeTopicId,
    hydrateFetchStatus,
    articles,
    getActionState,
  } = useStore();

  const isFetching =
    (fetchingTopicId === activeTopicId && activeTopicId !== null) ||
    (activeTopicId != null && getActionState(`task:fetch:${activeTopicId}`).status === "running");
  const lastFetchedLabel = useLastFetchedLabel(articles);

  // Periodic fallback status check — recovers fetch state after page refresh
  // or if the one-time hydrate call on mount was missed/failed.
  const isFetchingRef = useRef(isFetching);
  isFetchingRef.current = isFetching;
  useEffect(() => {
    if (!activeTopicId) return;
    let alive = true;

    const check = async () => {
      if (!alive) return;
      try {
        const { running } = await fetchFetchStatus(activeTopicId);
        if (!alive) return;
        const store = useStore.getState();
        if (running && store.fetchingTopicId !== activeTopicId) {
          // Backend is fetching but frontend lost the state — restore it
          store.setFetchingTopic(activeTopicId);
          void store.hydrateFetchStatus(activeTopicId);
        } else if (!running && store.fetchingTopicId === activeTopicId) {
          // Backend is done but frontend still shows fetching — clear stale state
          store.setFetchingTopic(null);
        }
      } catch {
        // silently ignore — no toast for background status checks
      }
    };

    // Immediate check on mount (recover state after page refresh)
    void check();
    // Then poll every 5 seconds as a safety net
    const interval = setInterval(check, 5000);
    return () => {
      alive = false;
      clearInterval(interval);
    };
  }, [activeTopicId]);

  async function handleFetch() {
    if (isFetching) return;
    setFetchingTopic(activeTopicId);
    try {
      const result = await runWithAction(
        `task:fetch:${activeTopicId ?? "all"}`,
        () => triggerFetch(activeTopicId),
        { errorMessage: "Failed to trigger fetch" },
      );
      if (result.status === "error") {
        useStore.getState().addToast("Failed to trigger fetch — please try again", "error");
        setFetchingTopic(null);
        return;
      }
    } catch {
      useStore.getState().addToast("Failed to trigger fetch — please try again", "error");
      setFetchingTopic(null);
      return;
    }
    void hydrateFetchStatus(activeTopicId);
  }

  return (
    <header className="flex flex-wrap items-center gap-2 px-3 py-2.5 sm:gap-3 sm:px-5 border-b border-border bg-surface/80 backdrop-blur-sm">
      <Link
        href="/"
        aria-label="Back to topics"
        className="p-1.5 rounded-lg text-muted hover:text-foreground hover:bg-surface-hover transition-colors"
      >
        <ArrowLeft className="w-4 h-4" aria-hidden="true" />
      </Link>

      <span
        className="w-3 h-3 rounded-full shrink-0"
        style={{ backgroundColor: topicColor }}
      />
      <div className="min-w-0 flex-1">
        <h1 className="truncate text-sm font-semibold tracking-tight sm:text-base">{topicName}</h1>
        <p className="hidden text-[11px] text-muted sm:block">Topic workspace</p>
      </div>

      <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
        {!isFetching && lastFetchedLabel && (
          <span
            className="hidden text-[11px] text-muted sm:inline"
            title="The time the latest news articles were fetched for this topic"
          >
            News fetched {lastFetchedLabel}
          </span>
        )}
        <button
          onClick={handleFetch}
          disabled={isFetching}
          aria-label={isFetching ? "Fetching in progress" : "Fetch latest news now"}
          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-accent text-white hover:bg-accent-hover disabled:opacity-50 transition-colors sm:gap-1.5 sm:px-3"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? "animate-spin" : ""}`} aria-hidden="true" />
          <span className="hidden sm:inline">{isFetching ? "Fetching…" : "Fetch Now"}</span>
          <span className="sm:hidden">{isFetching ? "..." : "Fetch"}</span>
        </button>
      </div>

      <button
        onClick={() => setChatOpen(!chatOpen)}
        aria-label={chatOpen ? "Close AI assistant" : "Open AI assistant"}
        aria-expanded={chatOpen}
        className={`p-2 rounded-lg transition-colors ${
          chatOpen
            ? "bg-accent text-white"
            : "text-muted hover:text-foreground hover:bg-surface-hover"
        }`}
      >
        <MessageSquare className="w-4 h-4" aria-hidden="true" />
      </button>

      <div className="mx-0.5 hidden h-6 w-px bg-border sm:mx-1 sm:block" />
      <ThemeToggle />
    </header>
  );
}
