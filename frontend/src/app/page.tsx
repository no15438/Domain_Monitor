"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { AlertTriangle, Loader2, Plus, Radar, RefreshCw, X } from "lucide-react";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  rectSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import ThemeToggle from "@/components/ThemeToggle";
import TopicCard from "@/components/TopicCard";
import {
  fetchTopicsOverview,
  fetchArchivedTopicsOverview,
  createTopic,
  reorderTopics,
  type TopicOverview,
} from "@/lib/api";
import { useStore } from "@/stores/useStore";
import { TOPIC_COLORS } from "@/lib/constants";
import { runWithAction } from "@/lib/api/shared";

const COLORS = TOPIC_COLORS;

// ── Sortable topic card wrapper ───────────────────────────────────────────────
function SortableTopicCard(props: React.ComponentProps<typeof TopicCard>) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: props.topic.id });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    zIndex: isDragging ? 50 : undefined,
    opacity: isDragging ? 0.5 : 1,
    position: "relative",
  };

  return (
    <div ref={setNodeRef} style={style}>
      <TopicCard
        {...props}
        dragHandleListeners={listeners}
        dragHandleAttributes={attributes}
        isDragging={isDragging}
      />
    </div>
  );
}

export default function Home() {
  const [topics, setTopics] = useState<TopicOverview[]>([]);
  const [archivedTopics, setArchivedTopics] = useState<TopicOverview[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [submittingCreate, setSubmittingCreate] = useState(false);
  const [createStep, setCreateStep] = useState<"form" | "confirm">("form");
  const [newName, setNewName] = useState("");
  const [newColor, setNewColor] = useState(COLORS[0]);
  const addToast = useStore((s) => s.addToast);
  const getActionState = useStore((s) => s.getActionState);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor),
  );
  const prevTopicsRef = useRef<TopicOverview[]>([]);

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    setTopics((prev) => {
      const oldIndex = prev.findIndex((t) => t.id === active.id);
      const newIndex = prev.findIndex((t) => t.id === over.id);
      if (oldIndex === -1 || newIndex === -1) return prev;
      const reordered = arrayMove(prev, oldIndex, newIndex);
      // Persist asynchronously; roll back on error
      reorderTopics(reordered.map((t) => t.id)).catch(() => {
        setTopics(prevTopicsRef.current);
        addToast("Failed to save topic order. Reverted to previous order.", "warn");
      });
      prevTopicsRef.current = reordered;
      return reordered;
    });
  }

  const loadTopics = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [data, archived] = await Promise.all([
        fetchTopicsOverview(24),
        fetchArchivedTopicsOverview(24),
      ]);
      setTopics(data.topics);
      prevTopicsRef.current = data.topics;
      setArchivedTopics(archived.topics);
    } catch (e) {
      if (process.env.NODE_ENV === "development") console.warn("[fetch]", e);
      setLoadError("Failed to load topics. Please retry.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTopics();
  }, [loadTopics]);

  async function handleCreateConfirmed() {
    const name = newName.trim();
    if (!name) return;
    try {
      if (submittingCreate) return;
      if (getActionState("ui:home:create-topic").status === "running") return;
      setSubmittingCreate(true);
      const result = await runWithAction(
        "ui:home:create-topic",
        () => createTopic(name, newColor),
        { errorMessage: "Failed to create topic" },
      );
      if (result.status === "error") {
        addToast(
          result.message === "Topic already exists"
            ? "A topic with this name already exists. Choose another name, restore an archived one, or delete the existing topic."
            : "Failed to create topic — please try again",
          "error",
        );
        return;
      }
      setNewName("");
      setCreating(false);
      setCreateStep("form");
      await loadTopics();
    } catch (e) {
      if (process.env.NODE_ENV === "development") console.warn("[create-topic]", e);
      addToast("Failed to create topic — please try again", "error");
    } finally {
      setSubmittingCreate(false);
    }
  }

  function openCreateForm() {
    setCreateStep("form");
    setCreating(true);
  }

  function closeCreateForm() {
    setCreating(false);
    setCreateStep("form");
  }

  function handleUpdated(id: number, patch: { name?: string; color?: string }) {
    setTopics((prev) =>
      prev.map((t) => (t.id === id ? { ...t, ...patch } : t))
    );
  }

  function handleDeleted(id: number) {
    setTopics((prev) => prev.filter((t) => t.id !== id));
    setArchivedTopics((prev) => prev.filter((t) => t.id !== id));
    void loadTopics();
  }

  function handleArchived() {
    void loadTopics();
  }

  function handleRestored() {
    void loadTopics();
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
        <div className="flex-1" />
        <ThemeToggle />
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
                onClick={openCreateForm}
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
                {createStep === "form" ? (
                  <div className="flex flex-col gap-3 p-4 rounded-xl border border-accent/30 bg-accent/5">
                    <p className="text-xs text-muted">New topic — choose a name and color.</p>
                    <div className="flex items-center gap-3 flex-wrap">
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
                        className="flex-1 min-w-48 px-3 py-2 rounded-lg text-sm bg-background border border-border focus:border-accent outline-none"
                      />
                      <button
                        type="button"
                        disabled={!newName.trim()}
                        onClick={() => {
                          if (!newName.trim()) return;
                          setCreateStep("confirm");
                        }}
                        className="px-4 py-2 rounded-lg text-xs font-medium bg-accent text-white hover:bg-accent-hover disabled:opacity-40"
                      >
                        Continue
                      </button>
                      <button
                        type="button"
                        onClick={closeCreateForm}
                        className="p-1.5 text-muted hover:text-foreground"
                        aria-label="Close"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col gap-3 p-4 rounded-xl border border-border bg-surface">
                    <p className="text-sm font-medium">
                      Create topic <span className="text-foreground">"{newName.trim()}"</span>?
                    </p>
                    <p className="text-xs text-muted">
                      You can archive it later to hide it from this list, or delete it permanently to remove all data.
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        disabled={submittingCreate || getActionState("ui:home:create-topic").status === "running"}
                        onClick={() => void handleCreateConfirmed()}
                        className="px-4 py-2 rounded-lg text-xs font-medium bg-accent text-white hover:bg-accent-hover disabled:opacity-50"
                      >
                        {submittingCreate || getActionState("ui:home:create-topic").status === "running" ? "Creating..." : "Create topic"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setCreateStep("form")}
                        className="px-4 py-2 rounded-lg text-xs font-medium border border-border text-muted hover:text-foreground hover:bg-surface-hover"
                      >
                        Back
                      </button>
                      <button
                        type="button"
                        onClick={closeCreateForm}
                        className="px-4 py-2 rounded-lg text-xs font-medium text-muted hover:text-foreground"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>

          {/* Loading */}
          {loading && (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="w-6 h-6 text-accent animate-spin" />
            </div>
          )}

          {!loading && loadError && (
            <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-surface px-6 py-12 text-center">
              <AlertTriangle className="mb-3 h-8 w-8 text-important" />
              <h3 className="mb-2 text-lg font-semibold">Topics unavailable</h3>
              <p className="mb-4 max-w-md text-sm text-muted">{loadError}</p>
              <button
                onClick={() => void loadTopics()}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover"
              >
                <RefreshCw className="h-4 w-4" />
                Retry
              </button>
            </div>
          )}

          {/* Empty state */}
          {!loading && !loadError && topics.length === 0 && archivedTopics.length === 0 && (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <Radar className="w-16 h-16 text-muted/30 mb-4" />
              <h3 className="text-lg font-semibold mb-2">No topics yet</h3>
              <p className="text-sm text-muted mb-4 max-w-md">
                Create your first topic to start monitoring an industry domain.
                Each topic tracks keywords, collects news, and generates AI insights.
              </p>
              <button
                onClick={openCreateForm}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-accent text-white hover:bg-accent-hover transition-colors"
              >
                <Plus className="w-4 h-4" />
                Create Your First Topic
              </button>
            </div>
          )}

          {!loading && !loadError && topics.length === 0 && archivedTopics.length > 0 && (
            <p className="text-sm text-muted mb-6">
              No active topics. Restore one from the archive below, or create a new topic.
            </p>
          )}

          {/* Topic cards grid — sortable */}
          {!loading && !loadError && topics.length > 0 && (
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={handleDragEnd}
            >
              <SortableContext
                items={topics.map((t) => t.id)}
                strategy={rectSortingStrategy}
              >
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {topics.map((topic, i) => (
                    <motion.div
                      key={topic.id}
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.05 }}
                    >
                      <SortableTopicCard
                        topic={topic}
                        variant="active"
                        onUpdated={handleUpdated}
                        onDeleted={handleDeleted}
                        onArchived={handleArchived}
                      />
                    </motion.div>
                  ))}
                </div>
              </SortableContext>
            </DndContext>
          )}

          {!loading && !loadError && archivedTopics.length > 0 && (
            <section className="mt-10 pt-8 border-t border-border">
              <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-4">
                Archived topics
              </h2>
              <p className="text-xs text-muted mb-4 max-w-xl">
                Archived topics stay in the database but do not appear above. Restore one to resume monitoring, or delete permanently to free the name.
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {archivedTopics.map((topic, i) => (
                  <motion.div
                    key={topic.id}
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.04 }}
                    layout
                  >
                    <TopicCard
                      topic={topic}
                      variant="archived"
                      onUpdated={handleUpdated}
                      onDeleted={handleDeleted}
                      onRestored={handleRestored}
                    />
                  </motion.div>
                ))}
              </div>
            </section>
          )}
        </div>
      </main>
    </div>
  );
}
