"use client";

import { useState } from "react";
import {
  RefreshCw,
  Plus,
  X,
  Radar,
  MessageSquare,
} from "lucide-react";
import { useStore } from "@/stores/useStore";
import {
  fetchArticles,
  fetchKeywords,
  addKeyword,
  removeKeyword,
  triggerFetch,
} from "@/lib/api";
import FeedManager from "./FeedManager";

export default function Header() {
  const {
    keywords,
    setKeywords,
    setArticles,
    fetchingTopicId,
    setFetchingTopic,
    chatOpen,
    setChatOpen,
    articles,
    activeTopicId,
    refreshInsights,
  } = useStore();
  const isFetching = fetchingTopicId === activeTopicId && activeTopicId !== null;
  const [newKw, setNewKw] = useState("");
  const [showInput, setShowInput] = useState(false);

  async function handleFetch() {
    setFetchingTopic(activeTopicId);
    try {
      await triggerFetch(activeTopicId);
      const data = await fetchArticles(50, 0, activeTopicId);
      setArticles(data.articles);
      refreshInsights();
    } finally {
      setFetchingTopic(null);
    }
  }

  async function handleAdd() {
    const kw = newKw.trim();
    if (!kw) return;
    await addKeyword(kw, "", activeTopicId);
    setNewKw("");
    setShowInput(false);
    const data = await fetchKeywords(activeTopicId);
    setKeywords(data.keywords);
  }

  async function handleRemove(id: number) {
    await removeKeyword(id);
    const data = await fetchKeywords(activeTopicId);
    setKeywords(data.keywords);
  }

  return (
    <header className="flex items-center gap-3 px-5 py-3 border-b border-border bg-surface/80 backdrop-blur-sm">
      <Radar className="w-6 h-6 text-accent" />
      <h1 className="text-lg font-semibold tracking-tight mr-4">
        Domain Monitor
      </h1>

      <div className="flex items-center gap-2 flex-1 overflow-x-auto min-w-0">
        {keywords.map((kw) => (
          <span
            key={kw.id}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-accent/15 text-accent-hover whitespace-nowrap"
          >
            {kw.keyword}
            <button
              onClick={() => handleRemove(kw.id)}
              className="hover:text-negative transition-colors"
            >
              <X className="w-3 h-3" />
            </button>
          </span>
        ))}

        {showInput ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleAdd();
            }}
            className="flex items-center gap-1"
          >
            <input
              autoFocus
              value={newKw}
              onChange={(e) => setNewKw(e.target.value)}
              placeholder="keyword…"
              className="w-28 px-2 py-1 rounded-md text-xs bg-background border border-border focus:border-accent outline-none"
            />
            <button
              type="submit"
              className="px-2 py-1 rounded-md text-xs bg-accent text-white hover:bg-accent-hover"
            >
              Add
            </button>
            <button
              type="button"
              onClick={() => setShowInput(false)}
              className="text-muted hover:text-foreground"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </form>
        ) : (
          <button
            onClick={() => setShowInput(true)}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs text-muted hover:text-foreground hover:bg-surface-hover transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            Add keyword
          </button>
        )}
      </div>

      <FeedManager />

      <span className="text-xs text-muted whitespace-nowrap">
        {articles.length} articles
      </span>

      <button
        onClick={handleFetch}
        disabled={isFetching}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-accent text-white hover:bg-accent-hover disabled:opacity-50 transition-colors"
      >
        <RefreshCw
          className={`w-3.5 h-3.5 ${isFetching ? "animate-spin" : ""}`}
        />
        {isFetching ? "Fetching…" : "Fetch Now"}
      </button>

      <button
        onClick={() => setChatOpen(!chatOpen)}
        className={`p-2 rounded-lg transition-colors ${
          chatOpen
            ? "bg-accent text-white"
            : "text-muted hover:text-foreground hover:bg-surface-hover"
        }`}
      >
        <MessageSquare className="w-4 h-4" />
      </button>
    </header>
  );
}
