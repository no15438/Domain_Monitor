"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Plus, X, Layers } from "lucide-react";
import { useStore } from "@/stores/useStore";
import { createTopic, deleteTopic, fetchTopics } from "@/lib/api";
import { runWithAction } from "@/lib/api/shared";

const COLORS = [
  "#6366f1", "#8b5cf6", "#ec4899", "#f43f5e",
  "#f59e0b", "#22c55e", "#06b6d4", "#3b82f6",
];

export default function TopicTabs() {
  const { topics, setTopics, activeTopicId, setActiveTopicId, addToast, getActionState } = useStore();
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newColor, setNewColor] = useState(COLORS[0]);

  async function handleCreate() {
    const name = newName.trim();
    if (!name) return;
    const actionKey = "ui:topic-tabs:create";
    if (getActionState(actionKey).status === "running") return;
    const result = await runWithAction(actionKey, () => createTopic(name, newColor), {
      errorMessage: "Failed to create topic",
    });
    if (result.status === "error") {
      addToast(result.message || "Failed to create topic", "error");
      return;
    }
    setNewName("");
    setCreating(false);
    const data = await fetchTopics();
    setTopics(data.topics);
  }

  async function handleDelete(id: number, e: React.MouseEvent) {
    e.stopPropagation();
    const actionKey = `ui:topic-tabs:delete:${id}`;
    if (getActionState(actionKey).status === "running") return;
    const result = await runWithAction(actionKey, () => deleteTopic(id), {
      errorMessage: "Failed to delete topic",
    });
    if (result.status === "error") {
      addToast(result.message || "Failed to delete topic", "error");
      return;
    }
    if (activeTopicId === id) setActiveTopicId(null);
    const data = await fetchTopics();
    setTopics(data.topics);
  }

  return (
    <div className="flex items-center gap-1.5 px-5 py-2 border-b border-border overflow-x-auto">
      {/* All tab */}
      <button
        onClick={() => setActiveTopicId(null)}
        className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors ${
          activeTopicId === null
            ? "bg-foreground text-background"
            : "text-muted hover:text-foreground hover:bg-surface-hover"
        }`}
      >
        <Layers className="w-3.5 h-3.5" />
        All
      </button>

      {/* Topic tabs */}
      {topics.map((t) => (
        <motion.button
          key={t.id}
          layout
          onClick={() => setActiveTopicId(t.id)}
          className={`group inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors ${
            activeTopicId === t.id
              ? "bg-surface-hover text-foreground ring-1 ring-inset"
              : "text-muted hover:text-foreground hover:bg-surface-hover"
          }`}
          style={{
            ["--tw-ring-color" as string]:
              activeTopicId === t.id ? t.color : "transparent",
          }}
        >
          <span
            className="w-2 h-2 rounded-full shrink-0"
            style={{ backgroundColor: t.color }}
          />
          {t.name}
          <span
            onClick={(e) => handleDelete(t.id, e)}
            className={`ml-0.5 transition-opacity text-muted hover:text-negative ${
              getActionState(`ui:topic-tabs:delete:${t.id}`).status === "running"
                ? "opacity-100"
                : "opacity-0 group-hover:opacity-100"
            }`}
          >
            <X className="w-3 h-3" />
          </span>
        </motion.button>
      ))}

      {/* Create new */}
      {creating ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleCreate();
          }}
          className="inline-flex items-center gap-1.5"
        >
          <div className="flex gap-0.5">
            {COLORS.map((c) => (
              <button
                type="button"
                key={c}
                onClick={() => setNewColor(c)}
                className={`w-4 h-4 rounded-full transition-transform ${
                  newColor === c ? "scale-125 ring-1 ring-white" : "opacity-60 hover:opacity-100"
                }`}
                style={{ backgroundColor: c }}
              />
            ))}
          </div>
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Topic name…"
            className="w-28 px-2 py-1 rounded-md text-xs bg-background border border-border focus:border-accent outline-none"
          />
          <button
            type="submit"
            disabled={getActionState("ui:topic-tabs:create").status === "running"}
            className="px-2 py-1 rounded-md text-xs bg-accent text-white hover:bg-accent-hover"
          >
            {getActionState("ui:topic-tabs:create").status === "running" ? "Creating..." : "Create"}
          </button>
          <button
            type="button"
            onClick={() => setCreating(false)}
            className="text-muted hover:text-foreground"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </form>
      ) : (
        <button
          onClick={() => setCreating(true)}
          className="inline-flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs text-muted hover:text-foreground hover:bg-surface-hover transition-colors whitespace-nowrap"
        >
          <Plus className="w-3.5 h-3.5" />
          New Topic
        </button>
      )}
    </div>
  );
}
