"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
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

  const {
    setTopics,
    setKeywords,
    setActiveTopicId,
    chatOpen,
    hydrateFetchStatus,
  } = useStore();

  const [topic, setTopic] = useState<Topic | null>(null);
  const [loading, setLoading] = useState(true);
  const [briefCollapsed, setBriefCollapsed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setActiveTopicId(topicId);

    Promise.all([
      fetchTopics(),
      fetchKeywords(topicId),
    ]).then(([topicsData, kwData]) => {
      if (cancelled) return;
      setTopics(topicsData.topics);
      setKeywords(kwData.keywords);
      const found = topicsData.topics.find((t) => t.id === topicId);
      if (!found) {
        router.push("/");
        return;
      }
      setTopic(found);
      setLoading(false);
      void hydrateFetchStatus(topicId);
    }).catch((e) => {
      if (process.env.NODE_ENV === "development") console.warn("[topic-load]", e);
    });

    return () => {
      cancelled = true;
      setActiveTopicId(null);
    };
  }, [topicId, setActiveTopicId, setTopics, setKeywords, router, hydrateFetchStatus]);

  if (loading || !topic) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-6 h-6 text-accent animate-spin" />
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
          onToggle={() => setBriefCollapsed((v) => !v)}
        />
        <EventFeed />
        {chatOpen ? <ChatBot /> : <AnalysisPanel />}
      </main>
    </div>
  );
}
