"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Radar, Plus, X, Loader2 } from "lucide-react";
import TopicCard from "@/components/TopicCard";
import {
  fetchTopicsOverview,
  createTopic,
  type TopicOverview,
} from "@/lib/api";
import { useStore } from "@/stores/useStore";
import { TOPIC_COLORS } from "@/lib/constants";

const COLORS = TOPIC_COLORS;

export default function Home() {
  const [topics, setTopics] = useState<TopicOverview[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newColor, setNewColor] = useState(COLORS[0]);
  const addToast = useStore((s) => s.addToast);

  useEffect(() => {
    fetchTopicsOverview(24)
      .then((d) => { setTopics(d.topics); })
      .catch((e) => { if (process.env.NODE_ENV === "development") console.warn("[fetch]", e); })
      .finally(() => setLoading(false));
  }, []);

  async function handleCreate() {
    const name = newName.trim();
    if (!name) return;
    try {
      const result = await createTopic(name, newColor);
      if (result.status === "error") {
        addToast("Failed to create topic — please try again", "error");
        return;
      }
      setNewName("");
      setCreating(false);
      const d = await fetchTopicsOverview(24);
      setTopics(d.topics);
    } catch (e) {
      if (process.env.NODE_ENV === "development") console.warn("[create-topic]", e);
      addToast("Failed to create topic — please try again", "error");
    }
  }

  function handleUpdated(id: number, patch: { name?: string; color?: string }) {
    setTopics((prev) =>
      prev.map((t) => (t.id === id ? { ...t, ...patch } : t))
    );
  }

  function handleDeleted(id: number) {
    setTopics((prev) => prev.filter((t) => t.id !== id));
  }

  return (
    <div className="min-h-full flex flex-col">
      {/* Header */}
      <header className="flex items-center gap-3 px-6 py-4 border-b border-border bg-surface/80 backdrop-blur-sm">
        <Radar className="w-7 h-7 text-accent" />
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Domain Monitor</h1>
          <p className="text-[11px] text-muted">AI-powered industry intelligence</p>
        </div>
      </header>

      {/* Content */}
      <main className="flex-1 px-6 py-6">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-sm font-semibold text-muted uppercase tracking-wider">
              Your Topics
            </h2>
            {!creating && (
              <button
                onClick={() => setCreating(true)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-accent text-white hover:bg-accent-hover transition-colors"
              >
                <Plus className="w-3.5 h-3.5" />
                New Topic
              </button>
            )}
          </div>

          {/* Create form */}
          <AnimatePresence>
            {creating && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="overflow-hidden mb-6"
              >
                <form
                  onSubmit={(e) => { e.preventDefault(); handleCreate(); }}
                  className="flex items-center gap-3 p-4 rounded-xl border border-accent/30 bg-accent/5"
                >
                  <div className="flex gap-1">
                    {COLORS.map((c) => (
                      <button
                        type="button"
                        key={c}
                        onClick={() => setNewColor(c)}
                        className={`w-5 h-5 rounded-full transition-transform ${
                          newColor === c ? "scale-125 ring-2 ring-white" : "opacity-50 hover:opacity-100"
                        }`}
                        style={{ backgroundColor: c }}
                      />
                    ))}
                  </div>
                  <input
                    autoFocus
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    placeholder="Topic name (e.g. AI Agents, Cybersecurity)…"
                    className="flex-1 px-3 py-2 rounded-lg text-sm bg-background border border-border focus:border-accent outline-none"
                  />
                  <button
                    type="submit"
                    className="px-4 py-2 rounded-lg text-xs font-medium bg-accent text-white hover:bg-accent-hover"
                  >
                    Create
                  </button>
                  <button
                    type="button"
                    onClick={() => setCreating(false)}
                    className="p-1.5 text-muted hover:text-foreground"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </form>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Loading */}
          {loading && (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="w-6 h-6 text-accent animate-spin" />
            </div>
          )}

          {/* Empty state */}
          {!loading && topics.length === 0 && (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <Radar className="w-16 h-16 text-muted/30 mb-4" />
              <h3 className="text-lg font-semibold mb-2">No topics yet</h3>
              <p className="text-sm text-muted mb-4 max-w-md">
                Create your first topic to start monitoring an industry domain.
                Each topic tracks keywords, collects news, and generates AI insights.
              </p>
              <button
                onClick={() => setCreating(true)}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-accent text-white hover:bg-accent-hover transition-colors"
              >
                <Plus className="w-4 h-4" />
                Create Your First Topic
              </button>
            </div>
          )}

          {/* Topic cards grid */}
          {!loading && topics.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {topics.map((topic, i) => (
                <motion.div
                  key={topic.id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.05 }}
                  layout
                >
                  <TopicCard
                    topic={topic}
                    onUpdated={handleUpdated}
                    onDeleted={handleDeleted}
                  />
                </motion.div>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
