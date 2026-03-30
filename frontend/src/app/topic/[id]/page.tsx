"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AlertTriangle, Loader2, RefreshCw } from "lucide-react";
import TopicHeader from "@/components/TopicHeader";
import ResearchBriefPanel from "@/components/ResearchBriefPanel";
import EventFeed from "@/components/EventFeed";
import AnalysisPanel from "@/components/AnalysisPanel";
import ChatBot from "@/components/ChatBot";
import { useStore } from "@/stores/useStore";
import { fetchTopics, fetchKeywords, type Topic } from "@/lib/api";

export default function TopicDetailPage() {
  const params = useParams();
  const router = useRouter();
  const topicId = Number(params.id);
  const hasValidTopicId = Number.isFinite(topicId) && topicId > 0;

  const {
    setTopics,
    setKeywords,
    setActiveTopicId,
    chatOpen,
    hydrateFetchStatus,
    briefCollapsedByTopic,
    setBriefCollapsed,
  } = useStore();

  const [topic, setTopic] = useState<Topic | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const briefCollapsed = briefCollapsedByTopic[topicId] ?? false;

  const loadTopicWorkspace = useCallback(async () => {
    if (!hasValidTopicId) {
      setTopic(null);
      setNotFound(true);
      setError("Invalid topic id.");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    setNotFound(false);
    try {
      const [topicsData, kwData] = await Promise.all([
        fetchTopics(),
        fetchKeywords(topicId),
      ]);
      setTopics(topicsData.topics);
      setKeywords(kwData.keywords);
      const found = topicsData.topics.find((t) => t.id === topicId);
      if (!found) {
        setNotFound(true);
        setError("This topic does not exist or was removed.");
        router.push("/");
        return;
      }
      setTopic(found);
      void hydrateFetchStatus(topicId);
    } catch (e) {
      if (process.env.NODE_ENV === "development") console.warn("[topic-load]", e);
      setError("Failed to load this topic workspace. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [hasValidTopicId, hydrateFetchStatus, router, setKeywords, setTopics, topicId]);

  useEffect(() => {
    let cancelled = false;
    setActiveTopicId(topicId);

    void (async () => {
      if (cancelled) return;
      await loadTopicWorkspace();
    })();

    return () => {
      cancelled = true;
      setActiveTopicId(null);
    };
  }, [loadTopicWorkspace, setActiveTopicId, topicId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-6 h-6 text-accent animate-spin" />
      </div>
    );
  }

  if (!topic) {
    if (error) {
      return (
        <div className="flex h-full items-center justify-center px-6">
          <div className="max-w-md rounded-xl border border-border bg-surface p-6 text-center">
            <AlertTriangle className="mx-auto mb-3 h-8 w-8 text-important" />
            <h2 className="mb-2 text-base font-semibold">Topic workspace unavailable</h2>
            <p className="mb-4 text-sm text-muted">{error}</p>
            {notFound && (
              <p className="mb-3 text-xs text-muted">
                Redirecting you to the topic list.
              </p>
            )}
            <button
              onClick={() => void loadTopicWorkspace()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-accent-hover"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Retry
            </button>
          </div>
        </div>
      );
    }
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-sm text-muted">Opening topic workspace...</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <TopicHeader topicName={topic.name} topicColor={topic.color} />
      <main className="flex flex-1 overflow-hidden">
        <ResearchBriefPanel
          topic={topic}
          collapsed={briefCollapsed}
          onToggle={() => setBriefCollapsed(topicId, !briefCollapsed)}
        />
        <EventFeed />
        {chatOpen ? <ChatBot /> : <AnalysisPanel />}
      </main>
    </div>
  );
}
