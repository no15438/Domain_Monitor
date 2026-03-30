"use client";

import { useEffect, useState } from "react";
import { Rss, Plus, X, Loader2 } from "lucide-react";
import { useStore } from "@/stores/useStore";
import {
  fetchTopicFeeds,
  addTopicFeed,
  removeTopicFeed,
  type TopicFeed,
} from "@/lib/api";
import { runWithAction } from "@/lib/api/shared";

export default function FeedManager() {
  const { activeTopicId, addToast, getActionState } = useStore();
  const [feeds, setFeeds] = useState<TopicFeed[]>([]);
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [newUrl, setNewUrl] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (activeTopicId == null) {
      setFeeds([]);
      return;
    }
    fetchTopicFeeds(activeTopicId).then((d) => setFeeds(d.feeds)).catch((e) => { if (process.env.NODE_ENV === "development") console.warn("[fetch]", e); });
  }, [activeTopicId]);

  async function handleAdd() {
    const url = newUrl.trim();
    if (!url || activeTopicId == null) return;
    setLoading(true);
    try {
      await addTopicFeed(activeTopicId, url);
      setNewUrl("");
      setAdding(false);
      const d = await fetchTopicFeeds(activeTopicId);
      setFeeds(d.feeds);
    } catch (e) {
      if (process.env.NODE_ENV === "development") console.warn("[add-feed]", e);
      addToast("Failed to add RSS feed. Please try again.", "error");
    } finally {
      setLoading(false);
    }
  }

  async function handleRemove(id: number) {
    const actionKey = `ui:feed-manager:remove:${id}`;
    if (getActionState(actionKey).status === "running") return;
    try {
      await runWithAction(actionKey, () => removeTopicFeed(id), {
        errorMessage: "Failed to remove RSS feed",
      });
      if (activeTopicId != null) {
        const d = await fetchTopicFeeds(activeTopicId);
        setFeeds(d.feeds);
      }
    } catch (e) {
      if (process.env.NODE_ENV === "development") console.warn("[remove-feed]", e);
      addToast("Failed to remove RSS feed. Please try again.", "error");
    }
  }

  if (activeTopicId == null) return null;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs transition-colors ${
          open || feeds.length > 0
            ? "text-accent-hover bg-accent/15"
            : "text-muted hover:text-foreground hover:bg-surface-hover"
        }`}
      >
        <Rss className="w-3.5 h-3.5" />
        {feeds.length > 0 && <span>{feeds.length} feeds</span>}
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 w-80 bg-surface border border-border rounded-lg shadow-xl z-50 p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-foreground">RSS Feeds</span>
            <button
              onClick={() => setOpen(false)}
              aria-label="Close RSS feeds panel"
              className="text-muted hover:text-foreground"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          {feeds.length === 0 && !adding && (
            <p className="text-xs text-muted py-2">No RSS feeds configured.</p>
          )}

          <div className="space-y-1.5 max-h-40 overflow-y-auto">
            {feeds.map((f) => (
              <div
                key={f.id}
                className="flex items-center gap-2 text-xs px-2 py-1.5 rounded bg-background group"
              >
                <Rss className="w-3 h-3 text-accent shrink-0" />
                <span className="truncate flex-1" title={f.feed_url}>
                  {f.label || f.feed_url}
                </span>
                <button
                  onClick={() => handleRemove(f.id)}
                  disabled={getActionState(`ui:feed-manager:remove:${f.id}`).status === "running"}
                  aria-label={`Remove feed ${f.label || f.feed_url}`}
                  className="opacity-0 group-hover:opacity-100 text-muted hover:text-negative transition-opacity disabled:opacity-60"
                >
                  {getActionState(`ui:feed-manager:remove:${f.id}`).status === "running"
                    ? <Loader2 className="w-3 h-3 animate-spin" />
                    : <X className="w-3 h-3" />}
                </button>
              </div>
            ))}
          </div>

          {adding ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleAdd();
              }}
              className="mt-2 flex items-center gap-1.5"
            >
              <input
                autoFocus
                value={newUrl}
                onChange={(e) => setNewUrl(e.target.value)}
                placeholder="https://example.com/rss"
                className="flex-1 px-2 py-1 rounded-md text-xs bg-background border border-border focus:border-accent outline-none"
              />
              <button
                type="submit"
                disabled={loading}
                className="px-2 py-1 rounded-md text-xs bg-accent text-white hover:bg-accent-hover disabled:opacity-50"
              >
                {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : "Add"}
              </button>
              <button
                type="button"
                onClick={() => setAdding(false)}
                aria-label="Cancel adding RSS feed"
                className="text-muted hover:text-foreground"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </form>
          ) : (
            <button
              onClick={() => setAdding(true)}
              className="mt-2 inline-flex items-center gap-1 text-xs text-muted hover:text-foreground"
            >
              <Plus className="w-3 h-3" />
              Add RSS feed
            </button>
          )}
        </div>
      )}
    </div>
  );
}
